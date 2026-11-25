"""Find which transactions are the same purchase seen by different sources
(a receipt and its bank transaction) and merge them. Rules only, no AI.

Each source transaction is saved as its own transaction first; matching then
merges two existing transactions, the same way in every case
(docs/BACKEND_IMPLEMENTATION_DECISIONS.md #22)."""

import logging
import re
import sqlite3
from collections import Counter
from decimal import Decimal

from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.db.transaction_db import find_unmatched_transactions
from balanceai_backend.models.source_transaction import MatchedBy
from balanceai_backend.models.transaction import Transaction
from balanceai_backend.source_transactions.source_transaction_db import find_source_transactions
from balanceai_backend.source_transactions.transaction_grouping import (
    is_rejected_match,
    merge_transactions,
)

logger = logging.getLogger(__name__)

# The bank's date may be up to this many days before the receipt's (time zone,
# a charge taken before the receipt was printed) ...
_DAYS_BEFORE = 2
# ... or after it (posting takes 1-3 business days; weekends, holidays and
# merchants that send charges late stretch that).
_DAYS_AFTER = 7
# The bank's amount may be up to 30% higher than the receipt's: a tip, or a fee
# added after the receipt was printed. Never lower.
_MAX_OVER_RECEIPT = Decimal("0.30")
# Card-processor prefixes that banks put in front of merchant names.
_PROCESSOR_PREFIX = re.compile(r"^(sq|tst|sp|pp|paypal|py)\s*\*\s*")
# Plaid's detailed category for cash taken out at an ATM or teller. Its
# description names no merchant ("WITHDRAWAL 03/14"), so a withdrawal matches
# on the exact amount and the date alone.
_WITHDRAWAL = "TRANSFER_OUT_WITHDRAWAL"


def match_receipts_and_bank_transactions(
    receipt_transaction_ids: list[str] | None = None,
    account_ids: list[str] | None = None,
    conn: sqlite3.Connection = _default_conn,
) -> list[str]:
    """Merge each unmatched receipt with the unmatched bank transaction that is
    the same purchase, whichever arrived first. Tries the given receipts
    (after an upload), or every unmatched receipt on account_ids (after a
    sync), or every unmatched receipt. Merges a pair only when each is the
    other's only candidate and the user hasn't rejected it; anything
    ambiguous is logged and left alone.

    Returns:
        The ids of the merged (kept) transactions.
    """
    receipts = find_unmatched_transactions(
        "receipt", account_ids=account_ids, transaction_ids=receipt_transaction_ids, conn=conn
    )
    if not receipts:
        return []
    account_ids = list({r.account_id for r in receipts})
    bank_transactions = find_unmatched_transactions("plaid", account_ids=account_ids, conn=conn)
    withdrawals = {
        s.transaction_id
        for a in account_ids
        for s in find_source_transactions(
            account_id=a, source="plaid", category_detailed=_WITHDRAWAL, conn=conn
        )
        if s.transaction_id is not None
    }
    candidates = _find_candidates(receipts, bank_transactions, withdrawals, conn)
    return _merge_unambiguous(candidates, conn)


def _find_candidates(
    receipts: list[Transaction],
    bank_transactions: list[Transaction],
    withdrawals: set[str],
    conn: sqlite3.Connection,
) -> dict[str, list[Transaction]]:
    """For each receipt, the bank transactions that fit and weren't rejected.
    withdrawals: the ids of the bank transactions that are cash withdrawals."""
    return {
        r.transaction_id: [
            b
            for b in bank_transactions
            if _is_candidate(r, b, b.transaction_id in withdrawals)
            and not is_rejected_match(r.transaction_id, b.transaction_id, conn)
        ]
        for r in receipts
    }


def _merge_unambiguous(
    candidates: dict[str, list[Transaction]], conn: sqlite3.Connection
) -> list[str]:
    """Merge pairs that are each other's only candidate. E.g. receipts A
    ($12.50) and B ($5.00) with bank transactions X ($12.50) and Y ($5.00):
    A+X and B+Y merge. Two $5.00 receipts and one $5.00 bank transaction:
    nothing merges. Returns the kept ids."""
    receipts_per_bank_txn = Counter(
        b.transaction_id for found in candidates.values() for b in found
    )
    merged = []
    for receipt_id, found in candidates.items():
        if len(found) == 1 and receipts_per_bank_txn[found[0].transaction_id] == 1:
            merged.append(
                merge_transactions(receipt_id, found[0].transaction_id, MatchedBy.RULE, conn=conn)
            )
        elif found:
            logger.info(
                "Receipt transaction %s not matched: %d candidate bank transactions, "
                "or a candidate that fits other receipts too",
                receipt_id,
                len(found),
            )
    return merged


def _is_candidate(receipt: Transaction, bank_txn: Transaction, is_withdrawal: bool) -> bool:
    """Same account, money in the same direction, dates that match, and either
    the exact amount (a cash withdrawal, whose bank description names no
    merchant) or amounts and merchant names that match."""
    if not (
        receipt.account_id == bank_txn.account_id
        and (receipt.amount < 0) == (bank_txn.amount < 0)
        and _dates_match(receipt, bank_txn)
    ):
        return False
    if is_withdrawal:
        return receipt.amount == bank_txn.amount
    return _amounts_match(receipt.amount, bank_txn.amount) and _names_match(
        receipt.description, bank_txn.description
    )


def _dates_match(receipt: Transaction, bank_txn: Transaction) -> bool:
    """The bank's date from _DAYS_BEFORE before to _DAYS_AFTER after the receipt's."""
    days = (bank_txn.booking_date - receipt.booking_date).days
    return -_DAYS_BEFORE <= days <= _DAYS_AFTER


def _amounts_match(receipt_amount: Decimal, bank_amount: Decimal) -> bool:
    """The bank's amount equals the receipt's, or is above it by up to
    _MAX_OVER_RECEIPT."""
    receipt, bank = abs(receipt_amount), abs(bank_amount)
    return receipt <= bank <= receipt * (1 + _MAX_OVER_RECEIPT)


def _names_match(receipt_name: str, bank_name: str) -> bool:
    """After cleaning, one name contains the other, or their first words match.
    'Blue Bottle Coffee Roasters' ~ 'SQ *BLUE BOTTLE 1234'."""
    a, b = _clean_name(receipt_name), _clean_name(bank_name)
    if not a or not b:
        return False
    return a in b or b in a or a.split()[0] == b.split()[0]


def _clean_name(name: str) -> str:
    """Lowercase; drop a card-processor prefix ('SQ *'), digits and punctuation."""
    name = _PROCESSOR_PREFIX.sub("", name.lower().strip())
    return " ".join(re.sub(r"[^a-z ]", " ", name).split())
