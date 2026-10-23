import dataclasses
import datetime
import json
import sqlite3
from decimal import Decimal

from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.models.raw_transaction import Classification, ClassifiedBy, RawTransaction


def _serialize_classification(classification: Classification | None) -> str | None:
    return json.dumps(classification.to_dict()) if classification is not None else None


def _deserialize_classification(value: str | None) -> Classification | None:
    return Classification.from_dict(json.loads(value)) if value else None


def _build_transaction(row) -> RawTransaction:
    return RawTransaction(
        id=row["id"],
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
        classification=_deserialize_classification(row["classification"]),
    )


def find_raw_transactions(
    id: str | None = None,
    plaid_item_id: str | None = None,
    account_id: str | None = None,
    source: str | None = None,
    unclassified: bool = False,
    conn: sqlite3.Connection = _default_conn,
) -> list[RawTransaction]:
    """Find raw transactions, optionally filtered by id, plaid_item_id, account_id,
    and/or source. With unclassified=True, only those with no classification yet."""
    query = "SELECT * FROM raw_transactions WHERE 1=1"
    params: list = []
    if id is not None:
        query += " AND id = ?"
        params.append(id)
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


def upsert_raw_transaction(txn: RawTransaction, conn: sqlite3.Connection = _default_conn) -> None:
    """Insert a new raw transaction, or update it if the id already exists.

    Handles both Plaid's `added` and `modified` buckets with one function.

    On update only the source's fields are replaced. The classification is
    ours, so the stored one is kept, dropped, or flagged per
    _classification_to_keep, and txn.classification is ignored — use
    update_raw_transaction_classification to change it.
    """
    with conn:
        existing = find_raw_transactions(id=txn.id, conn=conn)
        classification = (
            _classification_to_keep(existing[0], txn) if existing else txn.classification
        )
        conn.execute(
            "INSERT INTO raw_transactions"
            " (id, source, plaid_item_id, account_id, plaid_account_id,"
            "  posting_date, description, amount, category, category_detailed,"
            "  category_confidence, pending, classification)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET"
            "  source=excluded.source, plaid_item_id=excluded.plaid_item_id,"
            "  account_id=excluded.account_id, plaid_account_id=excluded.plaid_account_id,"
            "  posting_date=excluded.posting_date, description=excluded.description,"
            "  amount=excluded.amount, category=excluded.category,"
            "  category_detailed=excluded.category_detailed,"
            "  category_confidence=excluded.category_confidence, pending=excluded.pending,"
            "  classification=excluded.classification",
            (
                txn.id,
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
            ),
        )


def update_raw_transaction_classification(
    transaction_id: str,
    classification: Classification | None,
    conn: sqlite3.Connection = _default_conn,
) -> None:
    """Set a raw transaction's classification, or clear it with None. Raises
    ValueError if the transaction doesn't exist."""
    with conn:
        cursor = conn.execute(
            "UPDATE raw_transactions SET classification = ? WHERE id = ?",
            (_serialize_classification(classification), transaction_id),
        )
    if cursor.rowcount == 0:
        raise ValueError(f"Raw transaction {transaction_id} not found")


def delete_raw_transaction(transaction_id: str, conn: sqlite3.Connection = _default_conn) -> None:
    """Delete a raw transaction by id.

    Silently no-ops if it doesn't exist — Plaid's `removed` bucket is a
    "make sure this is gone" signal from a bulk sync loop, not a targeted
    user action, so an unknown id isn't an error condition here the way it
    is for delete_plaid_item.
    """
    with conn:
        conn.execute("DELETE FROM raw_transactions WHERE id = ?", (transaction_id,))
