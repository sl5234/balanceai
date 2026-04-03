import datetime
import sqlite3
from decimal import Decimal

import pytest

from balanceai_backend.journals.journal_db import find_journal_entries, find_journals, save_journal, update_journal
from balanceai_backend.models.account import Account, AccountType
from balanceai_backend.models.bank import Bank
from balanceai_backend.models.journal import Journal, JournalAccount, JournalEntry

DDL = """
    CREATE TABLE journals (
        journal_id    TEXT PRIMARY KEY,
        account_id    TEXT NOT NULL,
        bank          TEXT NOT NULL,
        account_type  TEXT NOT NULL,
        description   TEXT NOT NULL DEFAULT '',
        start_date    TEXT NOT NULL,
        end_date      TEXT NOT NULL
    );

    CREATE TABLE journal_entries (
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
"""


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(DDL)
    yield conn
    conn.close()


@pytest.fixture
def sample_account():
    return Account(id="acct-1", bank=Bank.CHASE, account_type=AccountType.DEBIT)


@pytest.fixture
def sample_journal(sample_account):
    return Journal(
        account=sample_account,
        description="January journal",
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 1, 31),
    )


class TestSaveJournal:
    def test_inserts_journal(self, db, sample_journal):
        save_journal(sample_journal, db)

        row = db.execute("SELECT * FROM journals WHERE journal_id = ?", (sample_journal.journal_id,)).fetchone()
        assert row is not None

    def test_all_fields_persisted(self, db, sample_account, sample_journal):
        save_journal(sample_journal, db)

        row = db.execute("SELECT * FROM journals WHERE journal_id = ?", (sample_journal.journal_id,)).fetchone()
        assert row["journal_id"] == sample_journal.journal_id
        assert row["account_id"] == sample_account.id
        assert row["bank"] == Bank.CHASE.value
        assert row["account_type"] == AccountType.DEBIT.value
        assert row["description"] == sample_journal.description
        assert row["start_date"] == sample_journal.start_date.isoformat()
        assert row["end_date"] == sample_journal.end_date.isoformat()

    def test_duplicate_journal_id_raises(self, db, sample_journal):
        save_journal(sample_journal, db)

        with pytest.raises(sqlite3.IntegrityError):
            save_journal(sample_journal, db)

    def test_multiple_journals_saved(self, db, sample_account):
        j1 = Journal(
            account=sample_account,
            description="January",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
        )
        j2 = Journal(
            account=sample_account,
            description="February",
            start_date=datetime.date(2026, 2, 1),
            end_date=datetime.date(2026, 2, 28),
        )
        save_journal(j1, db)
        save_journal(j2, db)

        count = db.execute("SELECT COUNT(*) FROM journals").fetchone()[0]
        assert count == 2


def _make_entry(entry_id: str, date: datetime.date, amount: Decimal) -> JournalEntry:
    return JournalEntry(
        journal_entry_id=entry_id,
        date=date,
        account=JournalAccount.CASH,
        description="Test transaction",
        debit=amount,
        credit=Decimal("0"),
        category="groceries",
        tax=Decimal("0"),
        recipient="Self",
    )


def _insert_entry(db, entry: JournalEntry, journal_id: str) -> None:
    db.execute(
        "INSERT INTO journal_entries VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            entry.journal_entry_id,
            journal_id,
            entry.date.isoformat(),
            entry.account.value,
            entry.description,
            str(entry.debit),
            str(entry.credit),
            entry.category,
            str(entry.tax),
            entry.recipient,
        ),
    )
    db.commit()


class TestFindJournals:
    def test_returns_empty_list_when_no_journals(self, db):
        assert find_journals(conn=db) == []

    def test_returns_all_journals_with_no_filters(self, db, sample_account):
        j1 = Journal(
            account=sample_account,
            description="January",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
        )
        j2 = Journal(
            account=sample_account,
            description="February",
            start_date=datetime.date(2026, 2, 1),
            end_date=datetime.date(2026, 2, 28),
        )
        save_journal(j1, db)
        save_journal(j2, db)

        results = find_journals(conn=db)

        assert len(results) == 2

    def test_filter_by_journal_id(self, db, sample_account):
        j1 = Journal(
            account=sample_account,
            description="January",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
        )
        j2 = Journal(
            account=sample_account,
            description="February",
            start_date=datetime.date(2026, 2, 1),
            end_date=datetime.date(2026, 2, 28),
        )
        save_journal(j1, db)
        save_journal(j2, db)

        results = find_journals(journal_id=j1.journal_id, conn=db)

        assert len(results) == 1
        assert results[0].journal_id == j1.journal_id

    def test_filter_by_account_id(self, db):
        acct_a = Account(id="acct-a", bank=Bank.CHASE, account_type=AccountType.DEBIT)
        acct_b = Account(id="acct-b", bank=Bank.CHASE, account_type=AccountType.DEBIT)
        j_a = Journal(
            account=acct_a,
            description="Account A journal",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
        )
        j_b = Journal(
            account=acct_b,
            description="Account B journal",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
        )
        save_journal(j_a, db)
        save_journal(j_b, db)

        results = find_journals(account_id="acct-a", conn=db)

        assert len(results) == 1
        assert results[0].account.id == "acct-a"

    def test_filter_by_both_journal_id_and_account_id(self, db, sample_account):
        j = Journal(
            account=sample_account,
            description="January",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
        )
        save_journal(j, db)

        results = find_journals(journal_id=j.journal_id, account_id=sample_account.id, conn=db)

        assert len(results) == 1
        assert results[0].journal_id == j.journal_id

    def test_filter_by_both_mismatched(self, db, sample_account):
        j = Journal(
            account=sample_account,
            description="January",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
        )
        save_journal(j, db)

        results = find_journals(journal_id=j.journal_id, account_id="wrong-account", conn=db)

        assert results == []

    def test_unknown_journal_id_returns_empty(self, db):
        assert find_journals(journal_id="nonexistent", conn=db) == []

    def test_unknown_account_id_returns_empty(self, db):
        assert find_journals(account_id="nonexistent", conn=db) == []

    def test_results_ordered_by_start_date(self, db, sample_account):
        j_mar = Journal(
            account=sample_account,
            description="March",
            start_date=datetime.date(2026, 3, 1),
            end_date=datetime.date(2026, 3, 31),
        )
        j_jan = Journal(
            account=sample_account,
            description="January",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
        )
        j_feb = Journal(
            account=sample_account,
            description="February",
            start_date=datetime.date(2026, 2, 1),
            end_date=datetime.date(2026, 2, 28),
        )
        save_journal(j_mar, db)
        save_journal(j_jan, db)
        save_journal(j_feb, db)

        results = find_journals(conn=db)

        assert [r.start_date for r in results] == [
            datetime.date(2026, 1, 1),
            datetime.date(2026, 2, 1),
            datetime.date(2026, 3, 1),
        ]

    def test_entries_are_loaded(self, db, sample_journal):
        save_journal(sample_journal, db)
        entry = _make_entry("entry-1", datetime.date(2026, 1, 15), Decimal("42.50"))
        _insert_entry(db, entry, sample_journal.journal_id)

        results = find_journals(journal_id=sample_journal.journal_id, conn=db)

        assert len(results[0].entries) == 1
        e = results[0].entries[0]
        assert e.journal_entry_id == "entry-1"
        assert e.debit == Decimal("42.50")

    def test_entries_belong_to_correct_journal(self, db, sample_account):
        j1 = Journal(
            account=sample_account,
            description="January",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
        )
        j2 = Journal(
            account=sample_account,
            description="February",
            start_date=datetime.date(2026, 2, 1),
            end_date=datetime.date(2026, 2, 28),
        )
        save_journal(j1, db)
        save_journal(j2, db)
        _insert_entry(db, _make_entry("entry-j1", datetime.date(2026, 1, 10), Decimal("10.00")), j1.journal_id)
        _insert_entry(db, _make_entry("entry-j2", datetime.date(2026, 2, 10), Decimal("20.00")), j2.journal_id)

        results = find_journals(journal_id=j1.journal_id, conn=db)

        assert len(results[0].entries) == 1
        assert results[0].entries[0].journal_entry_id == "entry-j1"

    def test_multiple_journals_for_same_account(self, db, sample_account):
        j1 = Journal(
            account=sample_account,
            description="January",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
        )
        j2 = Journal(
            account=sample_account,
            description="February",
            start_date=datetime.date(2026, 2, 1),
            end_date=datetime.date(2026, 2, 28),
        )
        save_journal(j1, db)
        save_journal(j2, db)

        results = find_journals(account_id=sample_account.id, conn=db)

        assert len(results) == 2
        assert {r.journal_id for r in results} == {j1.journal_id, j2.journal_id}


class TestFindJournalEntries:
    def test_raises_when_journal_not_found(self, db):
        with pytest.raises(ValueError, match="nonexistent"):
            find_journal_entries("nonexistent", conn=db)

    def test_returns_empty_list_when_no_entries(self, db, sample_journal):
        save_journal(sample_journal, db)

        assert find_journal_entries(sample_journal.journal_id, conn=db) == []

    def test_returns_all_entries_when_no_date_filter(self, db, sample_journal):
        save_journal(sample_journal, db)
        e1 = _make_entry("entry-1", datetime.date(2026, 1, 10), Decimal("10.00"))
        e2 = _make_entry("entry-2", datetime.date(2026, 1, 20), Decimal("20.00"))
        _insert_entry(db, e1, sample_journal.journal_id)
        _insert_entry(db, e2, sample_journal.journal_id)

        results = find_journal_entries(sample_journal.journal_id, conn=db)

        assert {e.journal_entry_id for e in results} == {"entry-1", "entry-2"}

    def test_filter_by_date_returns_matching_entries(self, db, sample_journal):
        save_journal(sample_journal, db)
        e1 = _make_entry("entry-1", datetime.date(2026, 1, 10), Decimal("10.00"))
        e2 = _make_entry("entry-2", datetime.date(2026, 1, 20), Decimal("20.00"))
        _insert_entry(db, e1, sample_journal.journal_id)
        _insert_entry(db, e2, sample_journal.journal_id)

        results = find_journal_entries(sample_journal.journal_id, date=datetime.date(2026, 1, 10), conn=db)

        assert len(results) == 1
        assert results[0].journal_entry_id == "entry-1"

    def test_filter_by_date_returns_empty_when_no_match(self, db, sample_journal):
        save_journal(sample_journal, db)
        _insert_entry(db, _make_entry("entry-1", datetime.date(2026, 1, 10), Decimal("10.00")), sample_journal.journal_id)

        results = find_journal_entries(sample_journal.journal_id, date=datetime.date(2026, 1, 15), conn=db)

        assert results == []

    def test_filter_by_date_returns_multiple_entries_same_date(self, db, sample_journal):
        save_journal(sample_journal, db)
        e1 = _make_entry("entry-1", datetime.date(2026, 1, 10), Decimal("10.00"))
        e2 = _make_entry("entry-2", datetime.date(2026, 1, 10), Decimal("20.00"))
        _insert_entry(db, e1, sample_journal.journal_id)
        _insert_entry(db, e2, sample_journal.journal_id)

        results = find_journal_entries(sample_journal.journal_id, date=datetime.date(2026, 1, 10), conn=db)

        assert {e.journal_entry_id for e in results} == {"entry-1", "entry-2"}

    def test_entry_fields_are_correctly_mapped(self, db, sample_journal):
        save_journal(sample_journal, db)
        entry = JournalEntry(
            journal_entry_id="entry-full",
            date=datetime.date(2026, 1, 15),
            account=JournalAccount.CASH,
            description="Full field test",
            debit=Decimal("42.50"),
            credit=Decimal("0.00"),
            category="groceries",
            tax=Decimal("3.50"),
            recipient="Jane",
        )
        _insert_entry(db, entry, sample_journal.journal_id)

        results = find_journal_entries(sample_journal.journal_id, conn=db)

        assert len(results) == 1
        e = results[0]
        assert e.journal_entry_id == "entry-full"
        assert e.date == datetime.date(2026, 1, 15)
        assert e.account == JournalAccount.CASH
        assert e.description == "Full field test"
        assert e.debit == Decimal("42.50")
        assert e.credit == Decimal("0.00")
        assert e.category == "groceries"
        assert e.tax == Decimal("3.50")
        assert e.recipient == "Jane"

    def test_null_recipient_defaults_to_self(self, db, sample_journal):
        from balanceai_backend.models.journal import RECIPIENT_SELF
        save_journal(sample_journal, db)
        db.execute(
            "INSERT INTO journal_entries VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("entry-null-recip", sample_journal.journal_id, "2026-01-10", "cash", "test", "5.00", "0", None, "0", None),
        )
        db.commit()

        results = find_journal_entries(sample_journal.journal_id, conn=db)

        assert results[0].recipient == RECIPIENT_SELF

    def test_entries_ordered_by_date(self, db, sample_journal):
        save_journal(sample_journal, db)
        _insert_entry(db, _make_entry("entry-3", datetime.date(2026, 1, 30), Decimal("30.00")), sample_journal.journal_id)
        _insert_entry(db, _make_entry("entry-1", datetime.date(2026, 1, 10), Decimal("10.00")), sample_journal.journal_id)
        _insert_entry(db, _make_entry("entry-2", datetime.date(2026, 1, 20), Decimal("20.00")), sample_journal.journal_id)

        results = find_journal_entries(sample_journal.journal_id, conn=db)

        assert [e.journal_entry_id for e in results] == ["entry-1", "entry-2", "entry-3"]

    def test_entries_scoped_to_journal(self, db, sample_account):
        j1 = Journal(
            account=sample_account,
            description="January",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
        )
        j2 = Journal(
            account=sample_account,
            description="February",
            start_date=datetime.date(2026, 2, 1),
            end_date=datetime.date(2026, 2, 28),
        )
        save_journal(j1, db)
        save_journal(j2, db)
        _insert_entry(db, _make_entry("entry-j1", datetime.date(2026, 1, 10), Decimal("10.00")), j1.journal_id)
        _insert_entry(db, _make_entry("entry-j2", datetime.date(2026, 2, 10), Decimal("20.00")), j2.journal_id)

        results = find_journal_entries(j1.journal_id, conn=db)

        assert len(results) == 1
        assert results[0].journal_entry_id == "entry-j1"


class TestUpdateJournal:
    def test_updates_journal_metadata(self, db, sample_journal):
        save_journal(sample_journal, db)
        sample_journal.description = "Updated description"
        sample_journal.end_date = datetime.date(2026, 1, 30)

        update_journal(sample_journal, db)

        row = db.execute("SELECT * FROM journals WHERE journal_id = ?", (sample_journal.journal_id,)).fetchone()
        assert row["description"] == "Updated description"
        assert row["end_date"] == "2026-01-30"

    def test_replaces_entries(self, db, sample_journal):
        entry1 = _make_entry("entry-1", datetime.date(2026, 1, 10), Decimal("10.00"))
        save_journal(sample_journal, db)
        db.execute(
            "INSERT INTO journal_entries VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("entry-1", sample_journal.journal_id, "2026-01-10", "cash", "old", "10.00", "0", None, "0", "Self"),
        )

        entry2 = _make_entry("entry-2", datetime.date(2026, 1, 20), Decimal("99.00"))
        sample_journal.entries = [entry2]
        update_journal(sample_journal, db)

        rows = db.execute("SELECT * FROM journal_entries WHERE journal_id = ?", (sample_journal.journal_id,)).fetchall()
        assert len(rows) == 1
        assert rows[0]["journal_entry_id"] == "entry-2"

    def test_raises_when_journal_not_found(self, db, sample_journal):
        with pytest.raises(ValueError, match=sample_journal.journal_id):
            update_journal(sample_journal, db)

    def test_journal_not_updated_if_entries_insert_fails(self, db, sample_journal):
        save_journal(sample_journal, db)
        # pre-insert an entry in another journal to cause a PRIMARY KEY collision
        other = Journal(
            account=sample_journal.account,
            description="Other",
            start_date=datetime.date(2026, 2, 1),
            end_date=datetime.date(2026, 2, 28),
        )
        save_journal(other, db)
        db.execute(
            "INSERT INTO journal_entries VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("entry-collision", other.journal_id, "2026-02-01", "cash", "other", "5.00", "0", None, "0", "Self"),
        )
        db.commit()

        # update sample_journal with a new description and an entry whose ID collides
        sample_journal.description = "Should not persist"
        collision_entry = _make_entry("entry-collision", datetime.date(2026, 1, 5), Decimal("20.00"))
        sample_journal.entries = [collision_entry]

        with pytest.raises(Exception):
            update_journal(sample_journal, db)

        # journal description must be unchanged
        row = db.execute("SELECT description FROM journals WHERE journal_id = ?", (sample_journal.journal_id,)).fetchone()
        assert row["description"] == "January journal"
