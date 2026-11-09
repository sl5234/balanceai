import sqlite3
from datetime import date

from balanceai_backend.db.connection import conn as _default_conn


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
