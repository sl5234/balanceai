"""A read-only connection for AI-written SQL, limited to the journal tables."""

import sqlite3
from pathlib import Path

from balanceai_backend.db.connection import DB_PATH

JOURNAL_TABLES = frozenset({"journals", "journal_lines"})

_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}


def _allow_only_reading_journal_tables(
    action: int, arg1: str | None, arg2: str | None, db: str | None, trigger: str | None
) -> int:
    """SQLite asks this before each step of a query; allow only reads of JOURNAL_TABLES."""
    if action == sqlite3.SQLITE_READ:
        return sqlite3.SQLITE_OK if arg1 in JOURNAL_TABLES else sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def open_readonly_journal_connection(path: Path) -> sqlite3.Connection:
    """Open the DB at path read-only, allowing reads of JOURNAL_TABLES only."""
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.set_authorizer(_allow_only_reading_journal_tables)
    return connection


readonly_journal_conn = open_readonly_journal_connection(DB_PATH)
