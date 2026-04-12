import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


def create_schema(connection: sqlite3.Connection) -> None:
    """Create all tables and indexes on the given connection."""
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS journals (
            journal_id    TEXT PRIMARY KEY,
            account_id    TEXT NOT NULL,
            bank          TEXT NOT NULL,
            account_type  TEXT NOT NULL,
            description   TEXT NOT NULL DEFAULT '',
            start_date    TEXT NOT NULL,
            end_date      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS journal_entries (
            journal_entry_id  TEXT PRIMARY KEY,
            journal_id        TEXT NOT NULL REFERENCES journals(journal_id) ON DELETE CASCADE,
            date              TEXT NOT NULL,
            account           TEXT NOT NULL,
            description       TEXT,
            debit             REAL NOT NULL,
            credit            REAL NOT NULL,
            category          TEXT,
            tax               REAL NOT NULL DEFAULT 0,
            recipient         TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_entries_journal_id ON journal_entries(journal_id);
        CREATE INDEX IF NOT EXISTS idx_entries_date       ON journal_entries(date);
        CREATE INDEX IF NOT EXISTS idx_entries_category   ON journal_entries(category);
        CREATE INDEX IF NOT EXISTS idx_entries_account    ON journal_entries(account);
        CREATE INDEX IF NOT EXISTS idx_entries_recipient  ON journal_entries(recipient);

        CREATE TABLE IF NOT EXISTS report_definitions (
            report_definition_id  TEXT PRIMARY KEY,
            name                  TEXT NOT NULL,
            prompt                TEXT NOT NULL,
            sql_template          TEXT NOT NULL,
            description           TEXT NOT NULL DEFAULT '',
            unparameterized_sql   TEXT,
            parameters            TEXT,
            created_at            TEXT NOT NULL
        );
    """)


def get_distinct_categories(connection: sqlite3.Connection) -> list[str | None]:
    """Return all distinct category values from journal_entries, including NULL."""
    rows = connection.execute("SELECT DISTINCT category FROM journal_entries").fetchall()
    return [row[0] for row in rows]


def get_distinct_accounts(connection: sqlite3.Connection) -> list[str | None]:
    """Return all distinct account values from journal_entries, including NULL."""
    rows = connection.execute("SELECT DISTINCT account FROM journal_entries").fetchall()
    return [row[0] for row in rows]


def get_schema_summary(connection: sqlite3.Connection) -> str:
    """Return a compact schema string derived from the live database.

    Queries PRAGMA table_info for each table so the output always reflects
    the actual schema without constraint noise (NOT NULL, DEFAULT, etc.).

    Example output:
        journals(journal_id TEXT, account_id TEXT, ...)
        journal_entries(journal_entry_id TEXT, journal_id TEXT, ...)
    """
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


def _apply_migrations(connection: sqlite3.Connection) -> None:
    """Apply incremental schema migrations for columns added after initial creation."""
    migrations = [
        # Rename sample_sql -> unparameterized_sql (SQLite 3.25+)
        "ALTER TABLE report_definitions RENAME COLUMN sample_sql TO unparameterized_sql",
        # Add parameters column for LLM-identified named params
        "ALTER TABLE report_definitions ADD COLUMN parameters TEXT",
    ]
    for sql in migrations:
        try:
            connection.execute(sql)
            connection.commit()
        except sqlite3.OperationalError:
            pass  # Already applied or column doesn't exist yet on a fresh schema


DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(DATA_DIR / "balanceai.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
create_schema(conn)
_apply_migrations(conn)
