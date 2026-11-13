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
            transaction_id      TEXT,   -- transactions.transaction_id it was booked from (NULL for
                                        -- the legacy entry tools, BL-9)
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
        CREATE INDEX IF NOT EXISTS idx_lines_transaction_id      ON journal_lines(transaction_id);
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

        -- One real transaction. Each source's source transaction for it points here
        -- (for now one each; matching will group them).
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id  TEXT PRIMARY KEY,      -- 'txn-<uuid>'
            account_id        TEXT REFERENCES bank_accounts(id) ON UPDATE CASCADE,
            transaction_date  TEXT,   -- when it happened (shown to the user)
            posted_date       TEXT,   -- when the bank posted it; NULL without a bank source
            amount            TEXT,
            description       TEXT,
            category          TEXT,   -- the source's category hint
            card_last4        TEXT,
            tax               TEXT,
            tip               TEXT,
            classification    TEXT,   -- ours, as JSON; NULL until classified
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS source_transactions (
            source_transaction_id    TEXT PRIMARY KEY,   -- ours, prefixed by source ('plaid-<uuid>')
            plaid_transaction_id  TEXT UNIQUE,        -- Plaid's transaction_id; NULL for other sources
            transaction_id           TEXT NOT NULL REFERENCES transactions(transaction_id),
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
            card_last4     TEXT,
            tax            TEXT,
            tip            TEXT,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_source_transactions_plaid_item_id ON source_transactions(plaid_item_id);
        CREATE INDEX IF NOT EXISTS idx_source_transactions_account_id    ON source_transactions(account_id);
        CREATE INDEX IF NOT EXISTS idx_source_transactions_posting_date  ON source_transactions(posting_date);
        CREATE INDEX IF NOT EXISTS idx_source_transactions_source        ON source_transactions(source);
        CREATE INDEX IF NOT EXISTS idx_source_transactions_plaid_transaction_id
            ON source_transactions(plaid_transaction_id);
        CREATE INDEX IF NOT EXISTS idx_source_transactions_transaction_id ON source_transactions(transaction_id);
    """)


def _check_schema_is_current(connection: sqlite3.Connection) -> None:
    """Stop on a database from before source transactions and transactions
    (it has a raw_transactions table): it has to be deleted and re-synced, not
    migrated. Runs before create_schema; a new database passes.

    Raises:
        RuntimeError: if the database has the old raw_transactions table.
    """
    old = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'raw_transactions'"
    ).fetchone()
    if old:
        raise RuntimeError(
            "The database predates source transactions. Delete it and re-sync "
            "(link_bank, sync_bank_transactions, create_journal)."
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
