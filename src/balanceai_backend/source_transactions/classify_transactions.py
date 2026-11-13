"""Classify transactions — what each one is, in bookkeeping terms. The AI sees
each transaction as its source transactions (Plaid, receipt, statement).

Journal entries are generated from a transaction's classification by rule; see
docs/BACKEND_IMPLEMENTATION_DECISIONS.md #2.

Source transactions from the same source with the same description, direction
(money in or out), and bank account type are treated as the same kind of
transaction and share one classification; see
docs/BACKEND_IMPLEMENTATION_DECISIONS.md #4.
"""

import json
import logging
import random
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import anthropic
from pydantic import BaseModel

from balanceai_backend.db.bank_account_db import find_bank_accounts
from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.db.transaction_db import find_transactions, update_transaction
from balanceai_backend.models.journal import JournalAccount
from balanceai_backend.models.source_transaction import (
    Classification,
    ClassifiedBy,
    SourceTransaction,
)
from balanceai_backend.prompts.classify_transaction_prompt import classify_transactions_prompt
from balanceai_backend.services import anthropic as anthropic_service
from balanceai_backend.services import tavily as tavily_service
from balanceai_backend.source_transactions.source_transaction_db import find_source_transactions

logger = logging.getLogger(__name__)
# DEBUG so web search queries and results reach the link-bank server's log,
# which logs the package at INFO.
logger.setLevel(logging.DEBUG)

# How much of a web search result to log.
_LOGGED_RESULT_CHARS = 300

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


@dataclass
class _Item:
    """A transaction to classify, with its source transactions (Plaid first)."""

    transaction_id: str
    sources: list[SourceTransaction]


def classify_transactions(
    plaid_item_id: str | None = None, conn: sqlite3.Connection = _default_conn
) -> dict:
    """
    Classify every unclassified transaction with the AI, unless all of its
    source transactions are pending, _BATCH_SIZE transactions per call and up
    to _MAX_PARALLEL_CALLS calls at a time. With plaid_item_id, only
    transactions with a source transaction from that linked bank.

    A transaction with a source transaction matching an already-classified
    one's (same source, description, direction, and bank account type) copies
    that classification with no AI call. If its sources match different
    classifications, the user's wins, then the Plaid source's. Unclassified
    transactions that match each other are sent to the AI once, and its answer
    is saved on all of them.

    Each AI call is retried on rate limits and temporary errors. A batch that
    still fails is left unclassified and the rest carry on, except when the AI
    provider rejects our credentials, which stops the run.

    Safe to call repeatedly: anything left unclassified is picked up next time.

    Returns:
        dict with "classified" (how many this call classified), "unclassified"
        (transactions still unclassified and not waiting on a pending source,
        for that bank if given), and "errors" (a list of {"reason",
        "transactions"}: why transactions were left unclassified, and how
        many; empty if none).
    """
    account_types = {a.id: a.account_type.value for a in find_bank_accounts(conn=conn)}
    reusable = _find_classifications_to_reuse(account_types, conn)

    # Group unclassified transactions that share a classification; the rest are
    # groups of one.
    groups: dict[tuple, list[_Item]] = {}
    for item in _find_items_to_classify(plaid_item_id, conn):
        key = _build_match_key(item.sources[0], account_types) or ("single", item.transaction_id)
        groups.setdefault(key, []).append(item)

    classified = 0
    error_counts: dict[str, int] = {}  # reason -> how many transactions it left unclassified
    groups_for_ai: list[list[_Item]] = []
    copied: list[list[_Item]] = []
    for group in groups.values():
        found = _reusable_for(group[0], reusable, account_types)
        if found is not None:
            classified += _save_classification_to_all(group, found, conn)
            copied.append(group)
        else:
            groups_for_ai.append(group)
    if copied:
        logger.info("Copied existing classifications to transactions %s", _transaction_ids(copied))

    # Look up merchants the source wasn't sure about, once per description.
    web_context = _search_web([s for group in groups_for_ai for s in group[0].sources])

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
        "unclassified": len(_find_items_to_classify(plaid_item_id, conn)),
        "errors": [{"reason": reason, "transactions": n} for reason, n in error_counts.items()],
    }


def _normalize_description(description: str) -> str:
    return " ".join(description.lower().split())


def _build_match_key(source: SourceTransaction, account_types: dict[str, str]) -> tuple | None:
    """A label for "the same kind of transaction" from one source transaction:
    its source, cleaned-up description, money in or out, and bank account type.
    Keys are only compared within a source (Plaid to Plaid, receipt to
    receipt). None if it mustn't share a classification."""
    if source.category in _NO_REUSE_CATEGORIES:
        return None
    return (
        source.source,
        _normalize_description(source.description),
        source.amount < 0,
        account_types.get(source.account_id),
    )


def _sources_by_transaction(conn: sqlite3.Connection) -> dict[str, list[SourceTransaction]]:
    """Every transaction's source transactions, Plaid first."""
    sources: dict[str, list[SourceTransaction]] = {}
    for source in find_source_transactions(conn=conn):
        if source.transaction_id is not None:
            sources.setdefault(source.transaction_id, []).append(source)
    for group in sources.values():
        group.sort(key=lambda s: s.source != "plaid")
    return sources


def _find_items_to_classify(plaid_item_id: str | None, conn: sqlite3.Connection) -> list[_Item]:
    """Unclassified transactions with their sources, skipping those whose
    sources are all pending. A pending Plaid transaction is replaced when it
    posts, so classifying it would be paid for twice; a receipt is never
    pending."""
    # TODO(BL-15): when the posted version arrives, it should join the pending
    # one's transaction (Plaid's pending_transaction_id), or the receipt's via
    # matching, so a classification made while pending isn't lost.
    sources = _sources_by_transaction(conn)
    items = [
        _Item(t.transaction_id, sources.get(t.transaction_id, []))
        for t in find_transactions(plaid_item_id=plaid_item_id, unclassified=True, conn=conn)
    ]
    return [i for i in items if i.sources and not all(s.pending for s in i.sources)]


def _find_classifications_to_reuse(
    account_types: dict[str, str], conn: sqlite3.Connection
) -> dict[tuple, Classification]:
    """Existing classifications to copy, by each source transaction's match
    key; for one key, the user's wins over the AI's, then the most recent."""
    sources = _sources_by_transaction(conn)
    reusable: dict[tuple, Classification] = {}
    for txn in find_transactions(conn=conn):
        if txn.classification is None:
            continue
        for source in sources.get(txn.transaction_id, []):
            key = _build_match_key(source, account_types)
            if key is None:
                continue
            current = reusable.get(key)
            if current is None or (
                txn.classification.classified_by == ClassifiedBy.USER
                or current.classified_by == ClassifiedBy.AI
            ):
                reusable[key] = txn.classification
    return reusable


def _reusable_for(
    item: _Item, reusable: dict[tuple, Classification], account_types: dict[str, str]
) -> Classification | None:
    """The classification to copy to this transaction, if any of its sources
    matches one: the user's first, then the Plaid source's (sources are Plaid
    first). None if none match, or if any source mustn't share one."""
    keys = [_build_match_key(source, account_types) for source in item.sources]
    if any(key is None for key in keys):
        return None
    hits = [reusable[key] for key in keys if key in reusable]
    if not hits:
        return None
    by_user = [hit for hit in hits if hit.classified_by == ClassifiedBy.USER]
    return (by_user or hits)[0]


def _index_answers(
    answer: _ClassifierAnswer, batch: list[list[_Item]]
) -> dict[int, _ClassifiedTransaction]:
    """The AI's answers by index. If it gave two different answers for the same
    group, the last one wins and a warning names the group's transactions."""
    answer_by_index: dict[int, _ClassifiedTransaction] = {}
    for classified in answer.classifications:
        earlier = answer_by_index.get(classified.index)
        if earlier is not None and earlier != classified and 0 <= classified.index < len(batch):
            logger.warning(
                "The AI gave conflicting answers for transactions %s: %s, then %s; using the last",
                _transaction_ids([batch[classified.index]]),
                earlier.model_dump(),
                classified.model_dump(),
            )
        answer_by_index[classified.index] = classified
    return answer_by_index


def _transaction_ids(groups: list[list[_Item]]) -> list[str]:
    """Source transaction ids, for logs: they trace back to Plaid or a receipt."""
    return [s.source_transaction_id for group in groups for item in group for s in item.sources]


def _count_transactions(groups: list[list[_Item]]) -> int:
    return sum(len(group) for group in groups)


def _add_error(error_counts: dict[str, int], reason: str, transactions: int) -> None:
    """Add to a reason's count of transactions left unclassified."""
    error_counts[reason] = error_counts.get(reason, 0) + transactions


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


def _search_web(sources: list[SourceTransaction]) -> dict[str, str]:
    """Web search results for merchants the source wasn't sure about, keyed by
    normalized description. One search per distinct description; a failed
    search is skipped."""
    results: dict[str, str | None] = {}
    for source in sources:
        key = _normalize_description(source.description)
        unsure = source.category is None or source.category_confidence in _WEB_SEARCH_CONFIDENCE
        if not unsure or key in results:
            continue
        query = f"What type of business is: {source.description}"
        try:
            results[key] = tavily_service.search(query)
        except Exception:
            logger.warning(
                "Web search failed for transaction %s", source.source_transaction_id, exc_info=True
            )
            results[key] = None
            continue
        logger.debug(
            "Web search for transaction %s | query: %s | result: %s",
            source.source_transaction_id,
            query,
            (results[key] or "")[:_LOGGED_RESULT_CHARS] or None,
        )
    return {key: result for key, result in results.items() if result}


def _build_ai_input(
    index: int, item: _Item, account_types: dict[str, str], web_context: dict[str, str]
) -> dict:
    """What the AI sees for one transaction: its source transactions, with no
    account numbers or ids."""
    return {
        "index": index,
        "sources": [_build_source_input(s, account_types, web_context) for s in item.sources],
    }


def _build_source_input(
    source: SourceTransaction, account_types: dict[str, str], web_context: dict[str, str]
) -> dict:
    fields = {
        "source": source.source,
        "description": source.description,
        "direction": "out" if source.amount < 0 else "in",
        "bank_account_type": account_types.get(source.account_id),
        "source_category": source.category,
        "plaid_category_detailed": source.category_detailed,
        "plaid_confidence": source.category_confidence,
        "web_context": web_context.get(_normalize_description(source.description)),
    }
    return {key: value for key, value in fields.items() if value is not None}


def _save_classification_to_all(
    group: list[_Item],
    source: Classification | _ClassifiedTransaction,
    conn: sqlite3.Connection,
) -> int:
    """Save the same classification on each transaction in a group, as set by
    the AI — even when copied from the user's, since the user classified that
    transaction, not these. Flagged for review when it has no category: the AI
    couldn't tell what the money was for, so its counter account is a guess."""
    with conn:
        for item in group:
            update_transaction(
                item.transaction_id,
                classification=Classification(
                    counter_account=source.counter_account,
                    category=source.category,
                    counterparty=source.counterparty,
                    classified_by=ClassifiedBy.AI,
                    needs_user_review=source.category is None,
                ),
                conn=conn,
            )
    return len(group)
