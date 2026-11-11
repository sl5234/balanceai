import logging
import os
import sqlite3
from pathlib import Path

from balanceai_backend.paths import SECRETS_DIR

logger = logging.getLogger(__name__)


def create_schema(connection: sqlite3.Connection) -> None:
    """Create all tables and indexes on the given connection."""
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS journals (
            journal_id    TEXT PRIMARY KEY,
            name          TEXT NOT NULL UNIQUE COLLATE NOCASE,
            description   TEXT NOT NULL DEFAULT '',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS journal_lines (
            journal_line_id   TEXT PRIMARY KEY,
            journal_id        TEXT NOT NULL REFERENCES journals(journal_id) ON DELETE CASCADE,
            date              TEXT NOT NULL,
            account           TEXT NOT NULL,
            description       TEXT,
            debit             REAL NOT NULL,
            credit            REAL NOT NULL,
            category          TEXT,
            tax               REAL NOT NULL DEFAULT 0,
            counterparty      TEXT,
            raw_transaction_id  TEXT,   -- raw_transactions.raw_transaction_id it was booked from
            bank_account_id     TEXT,
            journal_entry_id    TEXT,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_lines_journal_id       ON journal_lines(journal_id);
        CREATE INDEX IF NOT EXISTS idx_lines_date             ON journal_lines(date);
        CREATE INDEX IF NOT EXISTS idx_lines_category         ON journal_lines(category);
        CREATE INDEX IF NOT EXISTS idx_lines_account          ON journal_lines(account);
        CREATE INDEX IF NOT EXISTS idx_lines_counterparty     ON journal_lines(counterparty);
        CREATE INDEX IF NOT EXISTS idx_lines_raw_txn          ON journal_lines(raw_transaction_id);
        CREATE INDEX IF NOT EXISTS idx_lines_journal_entry_id ON journal_lines(journal_entry_id);

        -- Which bank accounts' transactions belong in which journal. UNIQUE keeps
        -- each bank account in at most one journal for now.
        CREATE TABLE IF NOT EXISTS journal_bank_accounts (
            journal_id       TEXT NOT NULL REFERENCES journals(journal_id) ON DELETE CASCADE,
            bank_account_id  TEXT NOT NULL UNIQUE REFERENCES bank_accounts(id),
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL,
            PRIMARY KEY (journal_id, bank_account_id)
        );

        CREATE TABLE IF NOT EXISTS report_definitions (
            report_definition_id  TEXT PRIMARY KEY,
            name                  TEXT NOT NULL,
            prompt                TEXT NOT NULL,
            sql_template          TEXT NOT NULL,
            description           TEXT NOT NULL DEFAULT '',
            unparameterized_sql   TEXT,
            parameters            TEXT,
            created_at            TEXT NOT NULL,
            updated_at            TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS plaid_items (
            item_id             TEXT PRIMARY KEY,
            access_token        TEXT NOT NULL,
            institution_id      TEXT,
            institution_name    TEXT,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS plaid_sync_cursors (
            item_id         TEXT PRIMARY KEY REFERENCES plaid_items(item_id) ON DELETE CASCADE,
            cursor          TEXT NOT NULL,
            last_synced_at  TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bank_accounts (
            id                    TEXT PRIMARY KEY,
            institution_name      TEXT NOT NULL,
            account_type          TEXT NOT NULL,
            last4                 TEXT NOT NULL,
            display_name          TEXT,
            plaid_institution_id  TEXT,
            plaid_item_id         TEXT REFERENCES plaid_items(item_id) ON DELETE SET NULL,
            plaid_account_id      TEXT UNIQUE,
            created_at            TEXT NOT NULL,
            updated_at            TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_bank_accounts_plaid_item_id ON bank_accounts(plaid_item_id);

        -- Unlinking a Plaid item keeps its bank accounts but clears their whole
        -- Plaid link, not just plaid_item_id — a stale plaid_account_id would
        -- block re-linking the same bank (which issues new Plaid account ids).
        CREATE TRIGGER IF NOT EXISTS trg_plaid_items_unlink_bank_accounts
        BEFORE DELETE ON plaid_items
        BEGIN
            UPDATE bank_accounts
            SET plaid_item_id = NULL, plaid_account_id = NULL
            WHERE plaid_item_id = OLD.item_id;
        END;

        CREATE TABLE IF NOT EXISTS raw_transactions (
            raw_transaction_id    TEXT PRIMARY KEY,   -- ours (UniqueIdGenerator), every source
            plaid_transaction_id  TEXT UNIQUE,        -- Plaid's transaction_id; NULL for other sources
            source         TEXT NOT NULL,
            plaid_item_id  TEXT REFERENCES plaid_items(item_id) ON DELETE SET NULL,
            account_id     TEXT NOT NULL REFERENCES bank_accounts(id) ON UPDATE CASCADE,
            plaid_account_id TEXT,
            posting_date   TEXT NOT NULL,
            description    TEXT NOT NULL,
            amount         TEXT NOT NULL,
            category       TEXT,
            category_detailed   TEXT,
            category_confidence TEXT,
            pending        INTEGER NOT NULL DEFAULT 0,
            classification TEXT,
            card_last4     TEXT,
            tax            TEXT,
            tip            TEXT,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_raw_transactions_plaid_item_id ON raw_transactions(plaid_item_id);
        CREATE INDEX IF NOT EXISTS idx_raw_transactions_account_id    ON raw_transactions(account_id);
        CREATE INDEX IF NOT EXISTS idx_raw_transactions_posting_date  ON raw_transactions(posting_date);
        CREATE INDEX IF NOT EXISTS idx_raw_transactions_source        ON raw_transactions(source);
        CREATE INDEX IF NOT EXISTS idx_raw_transactions_plaid_transaction_id
            ON raw_transactions(plaid_transaction_id);
    """)


def _check_schema_is_current(connection: sqlite3.Connection) -> None:
    """Stop on a database from before BL-16 (raw_transactions keyed by Plaid's
    id): it has to be deleted and re-synced, not migrated. Runs before
    create_schema, whose new indexes would fail on the old table; a new
    database (no raw_transactions yet) passes.

    Raises:
        RuntimeError: if raw_transactions has no raw_transaction_id column.
    """
    columns = {r[1] for r in connection.execute("PRAGMA table_info(raw_transactions)")}
    if columns and "raw_transaction_id" not in columns:
        raise RuntimeError(
            "The database predates BL-16 (raw transaction ids). Delete it and "
            "re-sync (link_bank, sync_bank_transactions, create_journal)."
        )


# BALANCEAI_DATA_DIR points elsewhere, e.g. a temp folder for tests.
DATA_DIR = Path(os.environ.get("BALANCEAI_DATA_DIR") or SECRETS_DIR / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "balanceai.db"

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
_check_schema_is_current(conn)
create_schema(conn)

try:
    os.chmod(DB_PATH, 0o600)
except OSError:
    pass  # e.g. Windows or a filesystem without chmod semantics
