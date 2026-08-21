import json
import sqlite3

from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.models.plaid_item import PlaidItem


def _build_item(row) -> PlaidItem:
    return PlaidItem(
        item_id=row["item_id"],
        access_token=row["access_token"],
        institution_id=row["institution_id"],
        institution_name=row["institution_name"],
        plaid_account_ids=json.loads(row["plaid_account_ids"]),
        our_account_ids=json.loads(row["our_account_ids"]),
        created_at=row["created_at"],
    )


def find_plaid_items(
    item_id: str | None = None,
    conn: sqlite3.Connection = _default_conn,
) -> list[PlaidItem]:
    """Find Plaid items, optionally filtered by item_id."""
    query = "SELECT * FROM plaid_items WHERE 1=1"
    params: list = []
    if item_id is not None:
        query += " AND item_id = ?"
        params.append(item_id)
    query += " ORDER BY created_at"
    rows = conn.execute(query, params).fetchall()
    return [_build_item(row) for row in rows]


def save_plaid_item(item: PlaidItem, conn: sqlite3.Connection = _default_conn) -> None:
    """Insert a new Plaid item into storage."""
    with conn:
        conn.execute(
            "INSERT INTO plaid_items"
            " (item_id, access_token, institution_id, institution_name,"
            "  plaid_account_ids, our_account_ids, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                item.item_id,
                item.access_token,
                item.institution_id,
                item.institution_name,
                json.dumps(item.plaid_account_ids),
                json.dumps(item.our_account_ids),
                item.created_at,
            ),
        )


def delete_plaid_item(item_id: str, conn: sqlite3.Connection = _default_conn) -> None:
    """Delete a Plaid item (and its sync cursor, via ON DELETE CASCADE). Raises ValueError if not found."""
    if not find_plaid_items(item_id=item_id, conn=conn):
        raise ValueError(f"Plaid item {item_id} not found")
    with conn:
        conn.execute("DELETE FROM plaid_items WHERE item_id = ?", (item_id,))
