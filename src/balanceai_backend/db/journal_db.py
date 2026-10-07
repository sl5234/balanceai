import datetime
import sqlite3
from decimal import Decimal

from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.models import Journal
from balanceai_backend.models.journal import RECIPIENT_SELF, JournalAccount, JournalEntry


def _build_journal(row, entry_rows) -> Journal:
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
        name=row["name"],
        description=row["description"],
        created_at=row["created_at"],
        entries=entries,
    )


def find_journals(
    journal_id: str | None = None,
    conn: sqlite3.Connection = _default_conn,
) -> list[Journal]:
    """Find journals, optionally filtered by journal_id."""
    query = "SELECT * FROM journals WHERE 1=1"
    params: list = []
    if journal_id is not None:
        query += " AND journal_id = ?"
        params.append(journal_id)
    query += " ORDER BY created_at"

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
            "INSERT INTO journals (journal_id, name, description, created_at) VALUES (?,?,?,?)",
            (
                journal.journal_id,
                journal.name,
                journal.description,
                journal.created_at,
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
            "UPDATE journals SET name=?, description=? WHERE journal_id=?",
            (
                updated.name,
                updated.description,
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
