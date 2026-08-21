import datetime
import sqlite3
from decimal import Decimal

from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.models.raw_transaction import RawTransaction


def _build_transaction(row) -> RawTransaction:
    return RawTransaction(
        id=row["id"],
        source=row["source"],
        plaid_item_id=row["plaid_item_id"],
        account_id=row["account_id"],
        posting_date=datetime.date.fromisoformat(row["posting_date"]),
        description=row["description"],
        amount=Decimal(row["amount"]),
        category=row["category"],
        pending=bool(row["pending"]),
    )


def find_raw_transactions(
    plaid_item_id: str | None = None,
    account_id: str | None = None,
    source: str | None = None,
    conn: sqlite3.Connection = _default_conn,
) -> list[RawTransaction]:
    """Find raw transactions, optionally filtered by plaid_item_id, account_id, and/or source."""
    query = "SELECT * FROM raw_transactions WHERE 1=1"
    params: list = []
    if plaid_item_id is not None:
        query += " AND plaid_item_id = ?"
        params.append(plaid_item_id)
    if account_id is not None:
        query += " AND account_id = ?"
        params.append(account_id)
    if source is not None:
        query += " AND source = ?"
        params.append(source)
    query += " ORDER BY posting_date"
    rows = conn.execute(query, params).fetchall()
    return [_build_transaction(row) for row in rows]


def upsert_raw_transaction(txn: RawTransaction, conn: sqlite3.Connection = _default_conn) -> None:
    """Insert a new raw transaction, or replace it if the id already exists.

    Handles both Plaid's `added` and `modified` buckets with one function —
    unlike the JSON-based Transaction store, SQLite's INSERT OR REPLACE keys
    off the primary key, so there's no need for a separate update path.
    """
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO raw_transactions"
            " (id, source, plaid_item_id, account_id, posting_date, description, amount, category, pending)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                txn.id,
                txn.source,
                txn.plaid_item_id,
                txn.account_id,
                txn.posting_date.isoformat(),
                txn.description,
                str(txn.amount),
                txn.category,
                int(txn.pending),
            ),
        )


def delete_raw_transaction(transaction_id: str, conn: sqlite3.Connection = _default_conn) -> None:
    """Delete a raw transaction by id.

    Silently no-ops if it doesn't exist — Plaid's `removed` bucket is a
    "make sure this is gone" signal from a bulk sync loop, not a targeted
    user action, so an unknown id isn't an error condition here the way it
    is for delete_plaid_item.
    """
    with conn:
        conn.execute("DELETE FROM raw_transactions WHERE id = ?", (transaction_id,))
