import sqlite3
from datetime import date

from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.db.readonly_journal_connection import readonly_journal_conn

HIDDEN = "[hidden description]"


def check_analyze_filters(
    start_date: date | None,
    end_date: date | None,
    account_id: str | None,
    journal_id: str | None,
    conn: sqlite3.Connection = _default_conn,
) -> None:
    """Reject analyze_financial_question filters that can't match anything,
    before any AI call."""
    if start_date and end_date and start_date > end_date:
        raise ValueError(f"The start date {start_date} is after the end date {end_date}.")
    if (
        journal_id
        and not conn.execute(
            "SELECT 1 FROM journals WHERE journal_id = ?", (journal_id,)
        ).fetchone()
    ):
        raise ValueError(f"No journal with id {journal_id}. See list_journals.")
    if (
        account_id
        and not conn.execute("SELECT 1 FROM bank_accounts WHERE id = ?", (account_id,)).fetchone()
    ):
        raise ValueError(f"No bank account with id {account_id}. See list_bank_accounts.")
    if (
        account_id
        and journal_id
        and not conn.execute(
            "SELECT 1 FROM journal_bank_accounts WHERE journal_id = ? AND bank_account_id = ?",
            (journal_id, account_id),
        ).fetchone()
    ):
        raise ValueError(f"Bank account {account_id} isn't in journal {journal_id}.")


def hide_descriptions(
    rows: list[dict], conn: sqlite3.Connection = readonly_journal_conn
) -> list[dict]:
    """Replace values that are a journal line's description (the bank's raw
    text, e.g. 'SQ *BLUE BOTTLE 0423 OAKLAND') with HIDDEN, whatever the
    column is called (SBL-5). A description that's also a counterparty is kept:
    it's the merchant's name, which is shared anyway. Only exact matches are
    caught; consent (SBL-6) is the guard against unusual queries."""
    descriptions = {r[0] for r in conn.execute("SELECT DISTINCT description FROM journal_lines")}
    counterparties = {r[0] for r in conn.execute("SELECT DISTINCT counterparty FROM journal_lines")}
    hidden = descriptions - counterparties
    return [
        {k: HIDDEN if isinstance(v, str) and v in hidden else v for k, v in row.items()}
        for row in rows
    ]
