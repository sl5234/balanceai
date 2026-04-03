import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(DATA_DIR / "balanceai.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")
conn.executescript("""
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
""")
