"""Everything that runs after new source transactions arrive: match receipts
with their bank transactions, classify, then book them into their journals."""

import logging
import sqlite3

from balanceai_backend.db.bank_account_db import find_bank_accounts
from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.db.journal_db import find_journals
from balanceai_backend.source_transactions.book_transactions import book_transactions
from balanceai_backend.source_transactions.classify_transactions import (
    classify_transactions,
)
from balanceai_backend.source_transactions.match_transactions import (
    match_receipts_and_bank_transactions,
)

logger = logging.getLogger(__name__)


def classify_and_book_transactions(
    plaid_item_id: str | None = None, conn: sqlite3.Connection = _default_conn
) -> dict:
    """
    Match receipts on the bank's accounts with their bank transactions,
    classify the bank's unclassified transactions, then book every journal
    holding one of its bank accounts. With no plaid_item_id, every bank and
    every journal.

    Booking problems are reported per journal rather than raised, so one
    journal's failure doesn't stop the others or lose the classification.

    Returns:
        dict with "matched" (receipts merged with their bank transaction),
        "classification" (see classify_transactions) and
        "booking": {journal_id: {"booked", "transfers_paired"} or {"error"}}.
    """
    # Receipts uploaded before their bank transaction synced are matched now (#22).
    account_ids = [a.id for a in find_bank_accounts(plaid_item_id=plaid_item_id, conn=conn)]
    matched = match_receipts_and_bank_transactions(account_ids=account_ids, conn=conn)
    classification = classify_transactions(plaid_item_id, conn)
    booking = _book_journals(plaid_item_id, conn)
    return {"matched": len(matched), "classification": classification, "booking": booking}


def _find_journal_ids(plaid_item_id: str | None, conn: sqlite3.Connection) -> list[str]:
    """The journals holding at least one of this bank's accounts."""
    bank_account_ids = {a.id for a in find_bank_accounts(plaid_item_id=plaid_item_id, conn=conn)}
    return [
        j.journal_id for j in find_journals(conn=conn) if bank_account_ids & set(j.bank_account_ids)
    ]


def _book_journals(plaid_item_id: str | None, conn: sqlite3.Connection) -> dict:
    booking: dict = {}
    for journal_id in _find_journal_ids(plaid_item_id, conn):
        try:
            booking[journal_id] = book_transactions(journal_id, conn)
        except (ValueError, sqlite3.Error) as e:
            logger.exception("Couldn't book journal %s", journal_id)
            booking[journal_id] = {"error": str(e)}
    return booking
