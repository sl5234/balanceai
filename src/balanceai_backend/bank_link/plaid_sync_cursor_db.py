import sqlite3

from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.models.plaid_sync_cursor import PlaidSyncCursor


def get_plaid_sync_cursor(item_id: str, conn: sqlite3.Connection = _default_conn) -> str | None:
    """Get the saved sync cursor for a Plaid item. Returns None if it has never synced."""
    row = conn.execute(
        "SELECT cursor FROM plaid_sync_cursors WHERE item_id = ?", (item_id,)
    ).fetchone()
    return row["cursor"] if row else None


def update_plaid_sync_cursor(
    cursor_state: PlaidSyncCursor,
    conn: sqlite3.Connection = _default_conn,
) -> None:
    """Upsert the sync cursor for a Plaid item — inserted on first sync, replaced on every sync after."""
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO plaid_sync_cursors (item_id, cursor, last_synced_at)"
            " VALUES (?, ?, ?)",
            (cursor_state.item_id, cursor_state.cursor, cursor_state.last_synced_at),
        )
