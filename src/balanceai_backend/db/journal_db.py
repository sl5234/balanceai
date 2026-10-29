import datetime
import sqlite3
from decimal import Decimal

from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.models import Journal
from balanceai_backend.models.journal import RECIPIENT_SELF, JournalAccount, JournalEntry


def _build_entry(r) -> JournalEntry:
    return JournalEntry(
        journal_line_id=r["journal_line_id"],
        date=datetime.date.fromisoformat(r["date"]),
        account=JournalAccount(r["account"]),
        description=r["description"],
        debit=Decimal(str(r["debit"])),
        credit=Decimal(str(r["credit"])),
        category=r["category"],
        tax=Decimal(str(r["tax"])),
        recipient=r["recipient"] or RECIPIENT_SELF,
        journal_entry_id=r["journal_entry_id"],
        raw_transaction_id=r["raw_transaction_id"],
        bank_account_id=r["bank_account_id"],
    )


def _build_journal(row, entry_rows, bank_account_ids: list[str]) -> Journal:
    return Journal(
        journal_id=row["journal_id"],
        name=row["name"],
        description=row["description"],
        created_at=row["created_at"],
        entries=[_build_entry(r) for r in entry_rows],
        bank_account_ids=bank_account_ids,
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
        bank_account_ids = [
            r["bank_account_id"]
            for r in conn.execute(
                "SELECT bank_account_id FROM journal_bank_accounts WHERE journal_id = ?"
                " ORDER BY bank_account_id",
                (row["journal_id"],),
            ).fetchall()
        ]
        journals.append(_build_journal(row, entry_rows, bank_account_ids))
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
    return [_build_entry(r) for r in rows]


def _insert_journal_entries(
    journal_id: str, entries: list[JournalEntry], conn: sqlite3.Connection
) -> None:
    conn.executemany(
        "INSERT INTO journal_entries (journal_line_id, journal_id, date, account,"
        " description, debit, credit, category, tax, recipient, journal_entry_id,"
        " raw_transaction_id, bank_account_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                entry.journal_line_id,
                journal_id,
                entry.date.isoformat(),
                entry.account.value,
                entry.description,
                str(entry.debit),
                str(entry.credit),
                entry.category,
                str(entry.tax),
                entry.recipient,
                entry.journal_entry_id,
                entry.raw_transaction_id,
                entry.bank_account_id,
            )
            for entry in entries
        ],
    )


def find_booked_raw_transactions(
    journal_id: str, conn: sqlite3.Connection = _default_conn
) -> dict[str, str]:
    """The raw transactions booked in a journal, each mapped to its entry's journal_entry_id."""
    rows = conn.execute(
        "SELECT DISTINCT raw_transaction_id, journal_entry_id FROM journal_entries"
        " WHERE journal_id = ? AND raw_transaction_id IS NOT NULL",
        (journal_id,),
    ).fetchall()
    return {r["raw_transaction_id"]: r["journal_entry_id"] for r in rows}


def add_journal_entry(
    journal_id: str, lines: list[JournalEntry], conn: sqlite3.Connection = _default_conn
) -> None:
    """Add one entry's lines to a journal. Doesn't commit; call inside the
    caller's transaction."""
    _insert_journal_entries(journal_id, lines, conn)


def add_journal_entries(
    journal_id: str, entries: list[list[JournalEntry]], conn: sqlite3.Connection = _default_conn
) -> None:
    """Add several entries, each a list of its lines. Doesn't commit; call
    inside the caller's transaction."""
    for lines in entries:
        add_journal_entry(journal_id, lines, conn)


def delete_journal_entry(journal_entry_id: str, conn: sqlite3.Connection = _default_conn) -> None:
    """Delete every line of an entry. Doesn't commit; call inside the caller's
    transaction."""
    conn.execute("DELETE FROM journal_entries WHERE journal_entry_id = ?", (journal_entry_id,))


def delete_journal_entries(
    journal_entry_ids: list[str], conn: sqlite3.Connection = _default_conn
) -> None:
    """Delete every line of several entries. Doesn't commit; call inside the
    caller's transaction."""
    for journal_entry_id in journal_entry_ids:
        delete_journal_entry(journal_entry_id, conn)


def delete_journal_entries_for_raw_transaction(
    raw_transaction_id: str, conn: sqlite3.Connection = _default_conn
) -> None:
    """Delete every entry with a line from this raw transaction, all lines of
    each, so a matched transfer's other side is left unbooked. Doesn't commit; call inside
    the caller's transaction."""
    conn.execute(
        "DELETE FROM journal_entries WHERE journal_entry_id IN"
        " (SELECT journal_entry_id FROM journal_entries WHERE raw_transaction_id = ?)",
        (raw_transaction_id,),
    )


def delete_journal_entries_for_bank_account(
    journal_id: str, bank_account_id: str, conn: sqlite3.Connection = _default_conn
) -> None:
    """Delete every entry with a line on this bank account in this journal, all
    lines of each. Doesn't commit; call inside the caller's transaction."""
    # Only the bank-side line names the account, so match the entry through it.
    conn.execute(
        "DELETE FROM journal_entries WHERE journal_entry_id IN"
        " (SELECT journal_entry_id FROM journal_entries"
        "  WHERE journal_id = ? AND bank_account_id = ?)",
        (journal_id, bank_account_id),
    )


def _current_bank_account_ids(journal_id: str, conn: sqlite3.Connection) -> list[str]:
    return [
        r["bank_account_id"]
        for r in conn.execute(
            "SELECT bank_account_id FROM journal_bank_accounts WHERE journal_id = ?",
            (journal_id,),
        )
    ]


def _save_bank_accounts(journal: Journal, conn: sqlite3.Connection) -> None:
    """Replace a journal's bank accounts with journal.bank_account_ids. Call
    inside the caller's transaction.

    Raises:
        ValueError: if a bank account doesn't exist or is in another journal.
    """
    for bank_account_id in journal.bank_account_ids:
        if not conn.execute(
            "SELECT 1 FROM bank_accounts WHERE id = ?", (bank_account_id,)
        ).fetchone():
            raise ValueError(f"Bank account {bank_account_id} not found")
        other = conn.execute(
            "SELECT j.name FROM journal_bank_accounts jba"
            " JOIN journals j ON j.journal_id = jba.journal_id"
            " WHERE jba.bank_account_id = ? AND jba.journal_id != ?",
            (bank_account_id, journal.journal_id),
        ).fetchone()
        if other:
            raise ValueError(
                f"Bank account {bank_account_id} is already in journal {other['name']!r}"
            )
    conn.execute("DELETE FROM journal_bank_accounts WHERE journal_id = ?", (journal.journal_id,))
    conn.executemany(
        "INSERT INTO journal_bank_accounts (journal_id, bank_account_id) VALUES (?, ?)",
        [(journal.journal_id, b) for b in dict.fromkeys(journal.bank_account_ids)],
    )


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
        _save_bank_accounts(journal, conn)


def delete_journal(journal_id: str, conn: sqlite3.Connection = _default_conn) -> None:
    """Delete a journal and all its entries. Raises ValueError if journal not found."""
    if not find_journals(journal_id=journal_id, conn=conn):
        raise ValueError(f"Journal {journal_id} not found")
    with conn:
        conn.execute("DELETE FROM journals WHERE journal_id = ?", (journal_id,))


def update_journal(updated: Journal, conn: sqlite3.Connection = _default_conn) -> None:
    """Replace a journal's data in storage by matching journal_id. Entries on a
    bank account that's no longer in the journal are deleted."""
    if not find_journals(journal_id=updated.journal_id, conn=conn):
        raise ValueError(f"Journal {updated.journal_id} not found")
    with conn:
        removed = set(_current_bank_account_ids(updated.journal_id, conn)) - set(
            updated.bank_account_ids
        )
        conn.execute(
            "UPDATE journals SET name=?, description=? WHERE journal_id=?",
            (
                updated.name,
                updated.description,
                updated.journal_id,
            ),
        )
        _save_bank_accounts(updated, conn)

        # TODO: replacing every entry goes away with update_journal's `entries`
        # (docs/BACKLOGS.md BL-9). Until then the removed accounts' entries are
        # deleted after it, or they'd be reinserted.
        conn.execute("DELETE FROM journal_entries WHERE journal_id = ?", (updated.journal_id,))
        _insert_journal_entries(updated.journal_id, updated.entries, conn)
        for bank_account_id in removed:
            delete_journal_entries_for_bank_account(updated.journal_id, bank_account_id, conn)
