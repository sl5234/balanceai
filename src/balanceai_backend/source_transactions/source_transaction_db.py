import dataclasses
import datetime
import sqlite3
from decimal import Decimal

from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.db.journal_db import delete_journal_entries_for_transaction
from balanceai_backend.db.transaction_db import (
    create_transaction,
    find_transactions,
    refresh_transaction,
    update_transaction,
)
from balanceai_backend.models.source_transaction import (
    Classification,
    ClassifiedBy,
    SourceTransaction,
)
from balanceai_backend.utils.general_util import utc_now_iso


def _build_source_transaction(row) -> SourceTransaction:
    return SourceTransaction(
        source_transaction_id=row["source_transaction_id"],
        plaid_transaction_id=row["plaid_transaction_id"],
        transaction_id=row["transaction_id"],
        source=row["source"],
        plaid_item_id=row["plaid_item_id"],
        plaid_account_id=row["plaid_account_id"],
        account_id=row["account_id"],
        posting_date=datetime.date.fromisoformat(row["posting_date"]),
        description=row["description"],
        amount=Decimal(row["amount"]),
        category=row["category"],
        category_detailed=row["category_detailed"],
        category_confidence=row["category_confidence"],
        pending=bool(row["pending"]),
        card_last4=row["card_last4"],
        tax=Decimal(row["tax"]) if row["tax"] is not None else None,
        tip=Decimal(row["tip"]) if row["tip"] is not None else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def find_source_transactions(
    source_transaction_id: str | None = None,
    plaid_transaction_id: str | None = None,
    plaid_item_id: str | None = None,
    account_id: str | None = None,
    source: str | None = None,
    transaction_id: str | None = None,
    conn: sqlite3.Connection = _default_conn,
) -> list[SourceTransaction]:
    """Find source transactions, optionally filtered by our id, Plaid's id,
    plaid_item_id, account_id, source, and/or the transaction they belong to."""
    query = "SELECT * FROM source_transactions WHERE 1=1"
    params: list = []
    if source_transaction_id is not None:
        query += " AND source_transaction_id = ?"
        params.append(source_transaction_id)
    if plaid_transaction_id is not None:
        query += " AND plaid_transaction_id = ?"
        params.append(plaid_transaction_id)
    if plaid_item_id is not None:
        query += " AND plaid_item_id = ?"
        params.append(plaid_item_id)
    if account_id is not None:
        query += " AND account_id = ?"
        params.append(account_id)
    if source is not None:
        query += " AND source = ?"
        params.append(source)
    if transaction_id is not None:
        query += " AND transaction_id = ?"
        params.append(transaction_id)
    query += " ORDER BY posting_date"
    rows = conn.execute(query, params).fetchall()
    return [_build_source_transaction(row) for row in rows]


def find_receipt_account_ids_for_card_last4(
    card_last4: str, conn: sqlite3.Connection = _default_conn
) -> list[str]:
    """The accounts that earlier receipts paid with this card were saved to."""
    rows = conn.execute(
        "SELECT DISTINCT account_id FROM source_transactions"
        " WHERE source = 'receipt' AND card_last4 = ?",
        (card_last4,),
    ).fetchall()
    return [r["account_id"] for r in rows]


def _classification_to_keep(
    existing: SourceTransaction,
    classification: Classification | None,
    incoming: SourceTransaction,
) -> Classification | None:
    """The classification the transaction keeps when one of its sources sends
    its source transaction again (existing -> incoming).

    Nothing changes unless the source changed something the classification was
    based on: description, amount, or the source's category or detailed
    category. A change in the source's confidence alone doesn't count. If it
    did change, the AI's classification is dropped so the transaction is
    classified again, and a user's is kept but flagged for the user to review.
    """
    if classification is None:
        return None
    if (
        existing.description,
        existing.amount,
        existing.category,
        existing.category_detailed,
    ) == (
        incoming.description,
        incoming.amount,
        incoming.category,
        incoming.category_detailed,
    ):
        return classification
    if classification.classified_by == ClassifiedBy.USER:
        return dataclasses.replace(classification, needs_user_review=True)
    return None


def upsert_source_transaction(
    txn: SourceTransaction, conn: sqlite3.Connection = _default_conn
) -> str:
    """Insert a new source transaction, or update the existing one: the same
    source_transaction_id, or, for a Plaid row, the same plaid_transaction_id.
    An existing row keeps its source_transaction_id and created_at.

    Handles both Plaid's `added` and `modified` buckets with one function.

    On update only the source's fields are replaced. The classification is the
    transaction's (ours): if the source changed something it was based on, it's
    kept, dropped, or flagged per _classification_to_keep. Use
    update_transaction to set it.

    If a booked transaction changes in a way its entry depends on (date,
    amount, description, bank account, or classification), the entry is
    deleted so the next booking run books it again.

    Returns:
        The stored source_transaction_id.
    """
    with conn:
        existing = _find_existing(txn, conn)
        if existing:
            txn = dataclasses.replace(
                txn,
                source_transaction_id=existing[0].source_transaction_id,
                transaction_id=existing[0].transaction_id,
            )
        else:
            txn = dataclasses.replace(txn, transaction_id=create_transaction(conn))
        # The classification is the transaction's; a source change may keep,
        # drop or flag it.
        before = _classification_of(existing[0].transaction_id, conn) if existing else None
        classification = _classification_to_keep(existing[0], before, txn) if existing else None
        if existing and (
            existing[0].posting_date,
            existing[0].amount,
            existing[0].description,
            existing[0].account_id,
        ) != (txn.posting_date, txn.amount, txn.description, txn.account_id):
            assert txn.transaction_id is not None  # copied from the stored row above
            delete_journal_entries_for_transaction(txn.transaction_id, conn)
        now = utc_now_iso()
        conn.execute(
            "INSERT INTO source_transactions"
            " (source_transaction_id, plaid_transaction_id, transaction_id, source, plaid_item_id,"
            "  account_id, plaid_account_id, posting_date, description, amount, category,"
            "  category_detailed, category_confidence, pending, card_last4,"
            "  tax, tip, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(source_transaction_id) DO UPDATE SET"
            "  plaid_transaction_id=excluded.plaid_transaction_id,"
            "  source=excluded.source, plaid_item_id=excluded.plaid_item_id,"
            "  account_id=excluded.account_id, plaid_account_id=excluded.plaid_account_id,"
            "  posting_date=excluded.posting_date, description=excluded.description,"
            "  amount=excluded.amount, category=excluded.category,"
            "  category_detailed=excluded.category_detailed,"
            "  category_confidence=excluded.category_confidence, pending=excluded.pending,"
            "  card_last4=excluded.card_last4,"
            "  tax=excluded.tax, tip=excluded.tip, updated_at=excluded.updated_at",
            (
                txn.source_transaction_id,
                txn.plaid_transaction_id,
                txn.transaction_id,
                txn.source,
                txn.plaid_item_id,
                txn.account_id,
                txn.plaid_account_id,
                txn.posting_date.isoformat(),
                txn.description,
                str(txn.amount),
                txn.category,
                txn.category_detailed,
                txn.category_confidence,
                int(txn.pending),
                txn.card_last4,
                str(txn.tax) if txn.tax is not None else None,
                str(txn.tip) if txn.tip is not None else None,
                now,
                now,
            ),
        )
        assert txn.transaction_id is not None
        refresh_transaction(txn.transaction_id, conn)
        if existing and classification != before:
            update_transaction(txn.transaction_id, classification=classification, conn=conn)
    return txn.source_transaction_id


def _classification_of(
    transaction_id: str | None, conn: sqlite3.Connection
) -> Classification | None:
    """The transaction's current classification."""
    found = find_transactions(transaction_id=transaction_id, conn=conn) if transaction_id else []
    return found[0].classification if found else None


def _find_existing(txn: SourceTransaction, conn: sqlite3.Connection) -> list[SourceTransaction]:
    """The stored row for txn: by source_transaction_id, else by plaid_transaction_id."""
    found = find_source_transactions(source_transaction_id=txn.source_transaction_id, conn=conn)
    if not found and txn.plaid_transaction_id:
        found = find_source_transactions(plaid_transaction_id=txn.plaid_transaction_id, conn=conn)
    return found


def delete_source_transaction(
    source_transaction_id: str, conn: sqlite3.Connection = _default_conn
) -> None:
    """Delete a source transaction by our id, and its entry.

    Silently no-ops if it doesn't exist — Plaid's `removed` bucket is a
    "make sure this is gone" signal from a bulk sync loop, not a targeted
    user action, so an unknown id isn't an error condition here the way it
    is for delete_plaid_item.
    """
    with conn:
        found = find_source_transactions(source_transaction_id=source_transaction_id, conn=conn)
        if found and found[0].transaction_id:
            delete_journal_entries_for_transaction(found[0].transaction_id, conn)
        conn.execute(
            "DELETE FROM source_transactions WHERE source_transaction_id = ?",
            (source_transaction_id,),
        )
        if found and found[0].transaction_id:
            refresh_transaction(found[0].transaction_id, conn)


def delete_source_transaction_by_plaid_id(
    plaid_transaction_id: str, conn: sqlite3.Connection = _default_conn
) -> None:
    """Delete the source transaction Plaid reported as removed, and its entry. No-op
    if there isn't one (the same reasoning as delete_source_transaction)."""
    found = find_source_transactions(plaid_transaction_id=plaid_transaction_id, conn=conn)
    if found:
        delete_source_transaction(found[0].source_transaction_id, conn=conn)
