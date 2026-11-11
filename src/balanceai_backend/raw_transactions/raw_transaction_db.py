import dataclasses
import datetime
import json
import sqlite3
from decimal import Decimal

from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.db.journal_db import delete_journal_entries_for_raw_transaction
from balanceai_backend.models.raw_transaction import Classification, ClassifiedBy, RawTransaction
from balanceai_backend.utils.general_util import utc_now_iso


def _serialize_classification(classification: Classification | None) -> str | None:
    return json.dumps(classification.to_dict()) if classification is not None else None


def _deserialize_classification(value: str | None) -> Classification | None:
    return Classification.from_dict(json.loads(value)) if value else None


def _build_transaction(row) -> RawTransaction:
    return RawTransaction(
        raw_transaction_id=row["raw_transaction_id"],
        plaid_transaction_id=row["plaid_transaction_id"],
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
        classification=_deserialize_classification(row["classification"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def find_raw_transactions(
    raw_transaction_id: str | None = None,
    plaid_transaction_id: str | None = None,
    plaid_item_id: str | None = None,
    account_id: str | None = None,
    source: str | None = None,
    unclassified: bool = False,
    conn: sqlite3.Connection = _default_conn,
) -> list[RawTransaction]:
    """Find raw transactions, optionally filtered by our id, Plaid's id,
    plaid_item_id, account_id, and/or source. With unclassified=True, only those
    with no classification yet."""
    query = "SELECT * FROM raw_transactions WHERE 1=1"
    params: list = []
    if raw_transaction_id is not None:
        query += " AND raw_transaction_id = ?"
        params.append(raw_transaction_id)
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
    if unclassified:
        query += " AND classification IS NULL"
    query += " ORDER BY posting_date"
    rows = conn.execute(query, params).fetchall()
    return [_build_transaction(row) for row in rows]


def find_receipt_account_ids_for_card_last4(
    card_last4: str, conn: sqlite3.Connection = _default_conn
) -> list[str]:
    """The accounts that earlier receipts paid with this card were saved to."""
    rows = conn.execute(
        "SELECT DISTINCT account_id FROM raw_transactions"
        " WHERE source = 'receipt' AND card_last4 = ?",
        (card_last4,),
    ).fetchall()
    return [r["account_id"] for r in rows]


def _classification_to_keep(
    existing: RawTransaction, incoming: RawTransaction
) -> Classification | None:
    """The classification an existing transaction keeps when its source sends it again.

    Nothing changes unless the source changed something the classification was
    based on: description, amount, or the source's category or detailed
    category. A change in the source's confidence alone doesn't count. If it
    did change, the AI's classification is dropped so the transaction is
    classified again, and a user's is kept but flagged for the user to review.
    """
    classification = existing.classification
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


def upsert_raw_transaction(txn: RawTransaction, conn: sqlite3.Connection = _default_conn) -> str:
    """Insert a new raw transaction, or update the existing one: the same
    raw_transaction_id, or, for a Plaid row, the same plaid_transaction_id.
    An existing row keeps its raw_transaction_id and created_at.

    Handles both Plaid's `added` and `modified` buckets with one function.

    On update only the source's fields are replaced. The classification is
    ours, so the stored one is kept, dropped, or flagged per
    _classification_to_keep, and txn.classification is ignored — use
    update_raw_transaction_classification to change it.

    If a booked transaction changes in a way its entry depends on (date,
    amount, description, bank account, or classification), the entry is
    deleted so the next booking run books it again.

    Returns:
        The stored raw_transaction_id.
    """
    with conn:
        existing = _find_existing(txn, conn)
        if existing:
            txn = dataclasses.replace(txn, raw_transaction_id=existing[0].raw_transaction_id)
        classification = (
            _classification_to_keep(existing[0], txn) if existing else txn.classification
        )
        if existing and (
            existing[0].posting_date,
            existing[0].amount,
            existing[0].description,
            existing[0].account_id,
            existing[0].classification,
        ) != (txn.posting_date, txn.amount, txn.description, txn.account_id, classification):
            delete_journal_entries_for_raw_transaction(txn.raw_transaction_id, conn)
        now = utc_now_iso()
        conn.execute(
            "INSERT INTO raw_transactions"
            " (raw_transaction_id, plaid_transaction_id, source, plaid_item_id, account_id,"
            "  plaid_account_id, posting_date, description, amount, category,"
            "  category_detailed, category_confidence, pending, classification, card_last4,"
            "  tax, tip, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(raw_transaction_id) DO UPDATE SET"
            "  plaid_transaction_id=excluded.plaid_transaction_id,"
            "  source=excluded.source, plaid_item_id=excluded.plaid_item_id,"
            "  account_id=excluded.account_id, plaid_account_id=excluded.plaid_account_id,"
            "  posting_date=excluded.posting_date, description=excluded.description,"
            "  amount=excluded.amount, category=excluded.category,"
            "  category_detailed=excluded.category_detailed,"
            "  category_confidence=excluded.category_confidence, pending=excluded.pending,"
            "  classification=excluded.classification, card_last4=excluded.card_last4,"
            "  tax=excluded.tax, tip=excluded.tip, updated_at=excluded.updated_at",
            (
                txn.raw_transaction_id,
                txn.plaid_transaction_id,
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
                _serialize_classification(classification),
                txn.card_last4,
                str(txn.tax) if txn.tax is not None else None,
                str(txn.tip) if txn.tip is not None else None,
                now,
                now,
            ),
        )
    return txn.raw_transaction_id


def _find_existing(txn: RawTransaction, conn: sqlite3.Connection) -> list[RawTransaction]:
    """The stored row for txn: by raw_transaction_id, else by plaid_transaction_id."""
    found = find_raw_transactions(raw_transaction_id=txn.raw_transaction_id, conn=conn)
    if not found and txn.plaid_transaction_id:
        found = find_raw_transactions(plaid_transaction_id=txn.plaid_transaction_id, conn=conn)
    return found


def update_raw_transaction_classification(
    raw_transaction_id: str,
    classification: Classification | None,
    conn: sqlite3.Connection = _default_conn,
) -> None:
    """Set a raw transaction's classification, or clear it with None, and
    delete its entry so the next booking run books it again. Raises
    ValueError if the transaction doesn't exist."""
    with conn:
        delete_journal_entries_for_raw_transaction(raw_transaction_id, conn)
        cursor = conn.execute(
            "UPDATE raw_transactions SET classification = ?, updated_at = ?"
            " WHERE raw_transaction_id = ?",
            (_serialize_classification(classification), utc_now_iso(), raw_transaction_id),
        )
    if cursor.rowcount == 0:
        raise ValueError(f"Raw transaction {raw_transaction_id} not found")


def delete_raw_transaction(
    raw_transaction_id: str, conn: sqlite3.Connection = _default_conn
) -> None:
    """Delete a raw transaction by our id, and its entry.

    Silently no-ops if it doesn't exist — Plaid's `removed` bucket is a
    "make sure this is gone" signal from a bulk sync loop, not a targeted
    user action, so an unknown id isn't an error condition here the way it
    is for delete_plaid_item.
    """
    with conn:
        delete_journal_entries_for_raw_transaction(raw_transaction_id, conn)
        conn.execute(
            "DELETE FROM raw_transactions WHERE raw_transaction_id = ?", (raw_transaction_id,)
        )


def delete_raw_transaction_by_plaid_id(
    plaid_transaction_id: str, conn: sqlite3.Connection = _default_conn
) -> None:
    """Delete the raw transaction Plaid reported as removed, and its entry. No-op
    if there isn't one (the same reasoning as delete_raw_transaction)."""
    found = find_raw_transactions(plaid_transaction_id=plaid_transaction_id, conn=conn)
    if found:
        delete_raw_transaction(found[0].raw_transaction_id, conn=conn)
