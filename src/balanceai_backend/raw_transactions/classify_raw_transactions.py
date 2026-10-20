"""Classify raw transactions — what each one is, in bookkeeping terms.

Journal entries are generated from a transaction's classification by rule; see
docs/BACKEND_IMPLEMENTATION_DECISIONS.md #2.

Transactions with the same description, direction (money in or out), and bank
account type are treated as the same kind of transaction and share one
classification; see docs/BACKEND_IMPLEMENTATION_DECISIONS.md #4.
"""

import json
import logging
import random
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
from pydantic import BaseModel

from balanceai_backend.db.bank_account_db import find_bank_accounts
from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.models.journal import JournalAccount
from balanceai_backend.models.raw_transaction import Classification, ClassifiedBy, RawTransaction
from balanceai_backend.prompts.classify_transaction_prompt import classify_transactions_prompt
from balanceai_backend.raw_transactions.raw_transaction_db import (
    find_raw_transactions,
    update_raw_transaction_classification,
)
from balanceai_backend.services import anthropic as anthropic_service
from balanceai_backend.services import tavily as tavily_service

logger = logging.getLogger(__name__)

MODEL_ID = "claude-haiku-4-5"
_BATCH_SIZE = 20
_MAX_PARALLEL_CALLS = 4
_MAX_ATTEMPTS = 10
_MAX_RETRY_WAIT_SECONDS = 30.0

# Transactions in these source categories never share a classification with
# another transaction: the same description can mean something different each
# time ("Zelle to Sam" may be a loan one month and rent the next).
_NO_REUSE_CATEGORIES = {"TRANSFER_IN", "TRANSFER_OUT", "LOAN_PAYMENTS", "INCOME"}

# Search the web for a merchant when the source gave no category, or wasn't sure
# of it.
_WEB_SEARCH_CONFIDENCE = {"LOW", "UNKNOWN"}


class _ClassifiedTransaction(BaseModel):
    """The AI's answer for one transaction."""

    index: int
    counter_account: JournalAccount
    category: str | None
    counterparty: str | None


class _ClassifierAnswer(BaseModel):
    """The AI's answer for a batch — the shape structured outputs enforces."""

    classifications: list[_ClassifiedTransaction]


class _StopClassifying(Exception):
    """An error no retry will fix, e.g. rejected credentials."""


class _StopSignal:
    """Set by the first batch whose error no retry will fix. Batches still
    waiting or retrying see it and stop without calling the AI."""

    def __init__(self) -> None:
        self.reason: str | None = None


def classify_raw_transactions(
    plaid_item_id: str | None = None, conn: sqlite3.Connection = _default_conn
) -> dict:
    """
    Classify every unclassified, non-pending raw transaction with the AI,
    _BATCH_SIZE transactions per call and up to _MAX_PARALLEL_CALLS calls at a
    time. With plaid_item_id, only that linked bank's transactions.

    A transaction matching an already-classified one (same description,
    direction, and bank account type), from any bank, copies its
    classification, preferring one the user set, with no AI call. Unclassified transactions that match each
    other are sent to the AI once, and its answer is saved on all of them.

    Each AI call is retried on rate limits and temporary errors. A batch that
    still fails is left unclassified and the rest carry on, except when the AI
    provider rejects our credentials, which stops the run.

    Safe to call repeatedly: anything left unclassified is picked up next time.

    Returns:
        dict with "classified" (how many this call classified), "unclassified"
        (non-pending transactions still unclassified, for that bank if given), and "errors" (a list of
        {"reason", "transactions"}: why transactions were left unclassified, and
        how many; empty if none).
    """
    account_types = {a.id: a.account_type.value for a in find_bank_accounts(conn=conn)}
    reusable = _find_classifications_to_reuse(account_types, conn)

    # Group unclassified transactions that share a classification; the rest are
    # groups of one.
    groups: dict[tuple, list[RawTransaction]] = {}
    for txn in _find_unclassified_posted_transactions(plaid_item_id, conn):
        key = _build_match_key(txn, account_types) or ("single", txn.id)
        groups.setdefault(key, []).append(txn)

    classified = 0
    error_counts: dict[str, int] = {}  # reason -> how many transactions it left unclassified
    groups_for_ai: list[list[RawTransaction]] = []
    copied: list[list[RawTransaction]] = []
    for key, group in groups.items():
        if key in reusable:
            classified += _save_classification_to_all(group, reusable[key], conn)
            copied.append(group)
        else:
            groups_for_ai.append(group)
    if copied:
        logger.info("Copied existing classifications to transactions %s", _transaction_ids(copied))

    # Look up merchants the source wasn't sure about, once per description.
    web_context = _search_web([group[0] for group in groups_for_ai])

    # Each batch holds up to _BATCH_SIZE groups; the AI sees one transaction per group.
    batches = [
        groups_for_ai[start : start + _BATCH_SIZE]
        for start in range(0, len(groups_for_ai), _BATCH_SIZE)
    ]
    stop_signal = _StopSignal()
    with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_CALLS) as executor:
        futures = {
            executor.submit(
                _classify_batch,
                # Only each group's first transaction is sent; fine while a group shares one answer.
                [
                    _build_ai_input(i, group[0], account_types, web_context)
                    for i, group in enumerate(batch)
                ],
                stop_signal,
            ): batch
            for batch in batches
        }
        # Results are saved here, on this thread, as each AI call finishes.
        for future in as_completed(futures):
            batch = futures[future]
            try:
                answer = future.result()
            except _StopClassifying as e:
                logger.warning("Not classified (%s): %s", e, _transaction_ids(batch))
                _add_error(error_counts, str(e), _count_transactions(batch))
                continue
            except Exception as e:
                logger.exception("Classifying transactions %s failed", _transaction_ids(batch))
                _add_error(
                    error_counts, f"Classifying a batch failed: {e}", _count_transactions(batch)
                )
                continue

            logger.info("The AI answered for transactions %s", _transaction_ids(batch))
            answer_by_index = _index_answers(answer, batch)
            skipped = [group for i, group in enumerate(batch) if i not in answer_by_index]
            if skipped:
                logger.warning("The AI skipped transactions %s", _transaction_ids(skipped))
                _add_error(
                    error_counts, "The AI skipped some transactions.", _count_transactions(skipped)
                )
            for i, group in enumerate(batch):
                if i in answer_by_index:
                    classified += _save_classification_to_all(group, answer_by_index[i], conn)

    return {
        "classified": classified,
        "unclassified": len(_find_unclassified_posted_transactions(plaid_item_id, conn)),
        "errors": [{"reason": reason, "transactions": n} for reason, n in error_counts.items()],
    }


def _normalize_description(description: str) -> str:
    return " ".join(description.lower().split())


def _build_match_key(txn: RawTransaction, account_types: dict[str, str]) -> tuple | None:
    """A label for "the same kind of transaction": cleaned-up description,
    money in or out, and bank account type. Transactions with the same match
    key share one classification. None if this transaction mustn't share one."""
    if txn.category in _NO_REUSE_CATEGORIES:
        return None
    return (
        _normalize_description(txn.description),
        txn.amount < 0,
        account_types.get(txn.account_id),
    )


def _find_classifications_to_reuse(
    account_types: dict[str, str], conn: sqlite3.Connection
) -> dict[tuple, Classification]:
    """Existing classifications to copy, by match key; the user's wins over the AI's."""
    reusable: dict[tuple, Classification] = {}
    for txn in find_raw_transactions(conn=conn):
        key = _build_match_key(txn, account_types)
        if key is None or txn.classification is None:
            continue
        # The user's overrides the AI's; otherwise the most recent transaction's wins.
        current = reusable.get(key)
        if current is None or (
            txn.classification.classified_by == ClassifiedBy.USER
            or current.classified_by == ClassifiedBy.AI
        ):
            reusable[key] = txn.classification
    return reusable


def _index_answers(
    answer: _ClassifierAnswer, batch: list[list[RawTransaction]]
) -> dict[int, _ClassifiedTransaction]:
    """The AI's answers by index. If it gave two different answers for the same
    group, the last one wins and a warning names the group's transactions."""
    answer_by_index: dict[int, _ClassifiedTransaction] = {}
    for classified in answer.classifications:
        earlier = answer_by_index.get(classified.index)
        if earlier is not None and earlier != classified and 0 <= classified.index < len(batch):
            logger.warning(
                "The AI gave conflicting answers for transactions %s: %s, then %s; using the last",
                [txn.id for txn in batch[classified.index]],
                earlier.model_dump(),
                classified.model_dump(),
            )
        answer_by_index[classified.index] = classified
    return answer_by_index


def _transaction_ids(groups: list[list[RawTransaction]]) -> list[str]:
    return [txn.id for group in groups for txn in group]


def _count_transactions(groups: list[list[RawTransaction]]) -> int:
    return sum(len(group) for group in groups)


def _add_error(error_counts: dict[str, int], reason: str, transactions: int) -> None:
    """Add to a reason's count of transactions left unclassified."""
    error_counts[reason] = error_counts.get(reason, 0) + transactions


def _find_unclassified_posted_transactions(
    plaid_item_id: str | None, conn: sqlite3.Connection
) -> list[RawTransaction]:
    """Pending transactions wait until they post — Plaid replaces them then."""
    return [
        t
        for t in find_raw_transactions(plaid_item_id=plaid_item_id, unclassified=True, conn=conn)
        if not t.pending
    ]


def _classify_batch(inputs: list[dict], stop_signal: _StopSignal) -> _ClassifierAnswer:
    """One AI call for a batch, retried on rate limits and temporary errors.

    Raises:
        _StopClassifying: the AI provider rejected our credentials.
        Exception: the batch failed for good (declined, a bad request, or
            still failing after _MAX_ATTEMPTS).
    """
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        if stop_signal.reason is not None:
            raise _StopClassifying(stop_signal.reason)
        try:
            answer = anthropic_service.parse(
                model_id=MODEL_ID,
                content=json.dumps(inputs),
                output_format=_ClassifierAnswer,
                system_instruction=classify_transactions_prompt(),
                max_output_tokens=4096,
                temperature=0.0,
            )
        # Order matters: these specific errors are subclasses of APIStatusError, so catch them first.
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            stop_signal.reason = f"The AI provider rejected our credentials: {e}"
            raise _StopClassifying(stop_signal.reason) from e
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as e:
            error: Exception = e
        except anthropic.APIStatusError as e:
            if e.status_code < 500:
                raise
            error = e
        else:
            if answer is None:
                raise ValueError("The AI declined to classify this batch.")
            return answer

        if attempt == _MAX_ATTEMPTS:
            raise RuntimeError(f"Gave up after {_MAX_ATTEMPTS} attempts: {error}") from error
        wait = min(2.0**attempt, _MAX_RETRY_WAIT_SECONDS) + random.uniform(0, 1)
        logger.warning(
            "Classification attempt %d failed (%s); retrying in %.0fs", attempt, error, wait
        )
        time.sleep(wait)
    raise AssertionError("unreachable")


def _search_web(txns: list[RawTransaction]) -> dict[str, str]:
    """Web search results for merchants the source wasn't sure about, keyed by
    normalized description. One search per distinct description; a failed
    search is skipped."""
    results: dict[str, str | None] = {}
    for txn in txns:
        key = _normalize_description(txn.description)
        unsure = txn.category is None or txn.category_confidence in _WEB_SEARCH_CONFIDENCE
        if not unsure or key in results:
            continue
        try:
            results[key] = tavily_service.search(f"What type of business is: {txn.description}")
        except Exception:
            logger.warning("Web search failed for transaction %s", txn.id, exc_info=True)
            results[key] = None
    return {key: result for key, result in results.items() if result}


def _build_ai_input(
    index: int, txn: RawTransaction, account_types: dict[str, str], web_context: dict[str, str]
) -> dict:
    """What the AI sees for one transaction — no account numbers or ids."""
    fields = {
        "index": index,
        "date": txn.posting_date.isoformat(),
        "description": txn.description,
        "amount": str(txn.amount),
        "bank_account_type": account_types.get(txn.account_id),
        "plaid_category": txn.category,
        "plaid_category_detailed": txn.category_detailed,
        "plaid_confidence": txn.category_confidence,
        "web_context": web_context.get(_normalize_description(txn.description)),
    }
    return {key: value for key, value in fields.items() if value is not None}


def _save_classification_to_all(
    group: list[RawTransaction],
    source: Classification | _ClassifiedTransaction,
    conn: sqlite3.Connection,
) -> int:
    """Save the same classification on each transaction in a group, as set by
    the AI — even when copied from the user's, since the user classified that
    transaction, not these."""
    for txn in group:
        update_raw_transaction_classification(
            txn.id,
            Classification(
                counter_account=source.counter_account,
                category=source.category,
                counterparty=source.counterparty,
                classified_by=ClassifiedBy.AI,
            ),
            conn=conn,
        )
    return len(group)
