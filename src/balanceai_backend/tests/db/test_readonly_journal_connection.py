import sqlite3

import pytest
from balanceai_backend.db.connection import conn
from balanceai_backend.db.readonly_journal_connection import readonly_journal_conn


def test_reads_journal_tables():
    readonly_journal_conn.execute(
        "SELECT j.name, SUM(l.debit) FROM journal_lines l"
        " JOIN journals j ON j.journal_id = l.journal_id GROUP BY j.name"
    ).fetchall()


def test_allows_ctes_and_subqueries():
    readonly_journal_conn.execute(
        "WITH t AS (SELECT debit FROM journal_lines) SELECT * FROM (SELECT * FROM t)"
    ).fetchall()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT access_token FROM plaid_items",
        "SELECT (SELECT access_token FROM plaid_items)",
        "SELECT description FROM source_transactions",
        "SELECT * FROM sqlite_master",
        "DELETE FROM journal_lines",
        "UPDATE journals SET name = 'x'",
        "DROP TABLE journals",
        "PRAGMA table_info(plaid_items)",
        "ATTACH DATABASE 'other.db' AS other",
    ],
)
def test_blocks_other_tables_and_writes(sql):
    with pytest.raises(sqlite3.DatabaseError):
        readonly_journal_conn.execute(sql)


def test_main_connection_is_unaffected():
    conn.execute("SELECT COUNT(*) FROM plaid_items").fetchone()
