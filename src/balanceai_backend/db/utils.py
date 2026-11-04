import sqlite3
from collections.abc import Iterable


def get_distinct_categories(connection: sqlite3.Connection) -> list[str | None]:
    """Return all distinct category values from journal_lines, including NULL."""
    rows = connection.execute("SELECT DISTINCT category FROM journal_lines").fetchall()
    return [row[0] for row in rows]


def get_distinct_accounts(connection: sqlite3.Connection) -> list[str | None]:
    """Return all distinct account values from journal_lines, including NULL."""
    rows = connection.execute("SELECT DISTINCT account FROM journal_lines").fetchall()
    return [row[0] for row in rows]


def get_schema_summary(connection: sqlite3.Connection, tables: Iterable[str] | None = None) -> str:
    """Return a compact schema string derived from the live database.

    Queries PRAGMA table_info for each table so the output always reflects
    the actual schema without constraint noise (NOT NULL, DEFAULT, etc.).

    tables: only these tables, in this order; every table when None.

    Example output:
        journals(journal_id TEXT, account_id TEXT, ...)
        journal_lines(journal_line_id TEXT, journal_id TEXT, ...)
    """
    if tables is None:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
    lines = []
    for table in tables:
        columns = connection.execute(f"PRAGMA table_info({table})").fetchall()
        col_defs = ", ".join(f"{col[1]} {col[2]}" for col in columns)
        lines.append(f"{table}({col_defs})")
    return "\n".join(lines)
