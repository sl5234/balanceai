import datetime
import sqlite3
from decimal import Decimal

from balanceai_backend.db import conn as _default_conn
from balanceai_backend.models import Journal
from balanceai_backend.models.account import Account, AccountType
from balanceai_backend.models.bank import Bank
from balanceai_backend.models.journal import JournalEntry, JournalAccount, RECIPIENT_SELF


def _build_journal(row, entry_rows) -> Journal:
    account = Account(
        id=row["account_id"],
        bank=Bank(row["bank"]),
        account_type=AccountType(row["account_type"]),
    )
    entries = [
        JournalEntry(
            journal_entry_id=r["journal_entry_id"],
            date=datetime.date.fromisoformat(r["date"]),
            account=JournalAccount(r["account"]),
            description=r["description"],
            debit=Decimal(str(r["debit"])),
            credit=Decimal(str(r["credit"])),
            category=r["category"],
            tax=Decimal(str(r["tax"])),
            recipient=r["recipient"] or RECIPIENT_SELF,
        )
        for r in entry_rows
    ]
    return Journal(
        journal_id=row["journal_id"],
        account=account,
        description=row["description"],
        start_date=datetime.date.fromisoformat(row["start_date"]),
        end_date=datetime.date.fromisoformat(row["end_date"]),
        entries=entries,
    )


def find_journals(
    journal_id: str | None = None,
    account_id: str | None = None,
    conn: sqlite3.Connection = _default_conn,
) -> list[Journal]:
    """Find journals, optionally filtered by journal_id and/or account_id."""
    query = "SELECT * FROM journals WHERE 1=1"
    params: list = []
    if journal_id is not None:
        query += " AND journal_id = ?"
        params.append(journal_id)
    if account_id is not None:
        query += " AND account_id = ?"
        params.append(account_id)
    query += " ORDER BY start_date"

    rows = conn.execute(query, params).fetchall()
    journals = []
    for row in rows:
        entry_rows = conn.execute(
            "SELECT * FROM journal_entries WHERE journal_id = ? ORDER BY date", (row["journal_id"],)
        ).fetchall()
        journals.append(_build_journal(row, entry_rows))
    return journals


def find_journal_entries(
    journal_id: str,
    date: datetime.date | None = None,
    conn: sqlite3.Connection = _default_conn,
) -> list[JournalEntry]:
    """Find entries for a journal, optionally filtered by date. Raises ValueError if journal not found."""
    if not find_journals(journal_id=journal_id, conn=conn):
        raise ValueError(f"Journal {journal_id} not found")
    query = "SELECT * FROM journal_entries WHERE journal_id = ?"
    params: list = [journal_id]
    if date is not None:
        query += " AND date = ?"
        params.append(date.isoformat())
    query += " ORDER BY date"
    rows = conn.execute(query, params).fetchall()
    return [
        JournalEntry(
            journal_entry_id=r["journal_entry_id"],
            date=datetime.date.fromisoformat(r["date"]),
            account=JournalAccount(r["account"]),
            description=r["description"],
            debit=Decimal(str(r["debit"])),
            credit=Decimal(str(r["credit"])),
            category=r["category"],
            tax=Decimal(str(r["tax"])),
            recipient=r["recipient"] or RECIPIENT_SELF,
        )
        for r in rows
    ]


def save_journal(journal: Journal, conn: sqlite3.Connection = _default_conn) -> None:
    """Insert a new journal into storage."""
    with conn:
        conn.execute(
            "INSERT INTO journals VALUES (?,?,?,?,?,?,?)",
            (
                journal.journal_id,
                journal.account.id,
                journal.account.bank.value,
                journal.account.account_type.value,
                journal.description,
                journal.start_date.isoformat(),
                journal.end_date.isoformat(),
            ),
        )


def delete_journal(journal_id: str, conn: sqlite3.Connection = _default_conn) -> None:
    """Delete a journal and all its entries. Raises ValueError if journal not found."""
    if not find_journals(journal_id=journal_id, conn=conn):
        raise ValueError(f"Journal {journal_id} not found")
    with conn:
        conn.execute("DELETE FROM journals WHERE journal_id = ?", (journal_id,))


def update_journal(updated: Journal, conn: sqlite3.Connection = _default_conn) -> None:
    """Replace a journal's data in storage by matching journal_id."""
    if not find_journals(journal_id=updated.journal_id, conn=conn):
        raise ValueError(f"Journal {updated.journal_id} not found")
    with conn:
        conn.execute(
            "UPDATE journals SET account_id=?, bank=?, account_type=?, description=?, start_date=?, end_date=? WHERE journal_id=?",
            (
                updated.account.id,
                updated.account.bank.value,
                updated.account.account_type.value,
                updated.description,
                updated.start_date.isoformat(),
                updated.end_date.isoformat(),
                updated.journal_id,
            ),
        )

        conn.execute("DELETE FROM journal_entries WHERE journal_id = ?", (updated.journal_id,))
        conn.executemany(
            "INSERT INTO journal_entries VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    entry.journal_entry_id,
                    updated.journal_id,
                    entry.date.isoformat(),
                    entry.account.value,
                    entry.description,
                    str(entry.debit),
                    str(entry.credit),
                    entry.category,
                    str(entry.tax),
                    entry.recipient,
                )
                for entry in updated.entries
            ],
        )