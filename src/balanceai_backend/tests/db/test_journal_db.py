import datetime
import sqlite3
from decimal import Decimal

import pytest
from balanceai_backend.db.connection import create_schema
from balanceai_backend.db.journal_db import (
    delete_journal,
    find_journal_entries,
    find_journals,
    save_journal,
    update_journal,
)
from balanceai_backend.models.journal import Journal, JournalAccount, JournalEntry


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_journal():
    return Journal(
        name="January journal",
    )


class TestSaveJournal:
    def test_inserts_journal(self, db, sample_journal):
        save_journal(sample_journal, db)

        row = db.execute(
            "SELECT * FROM journals WHERE journal_id = ?", (sample_journal.journal_id,)
        ).fetchone()
        assert row is not None

    def test_all_fields_persisted(self, db, sample_journal):
        save_journal(sample_journal, db)

        row = db.execute(
            "SELECT * FROM journals WHERE journal_id = ?", (sample_journal.journal_id,)
        ).fetchone()
        assert row["journal_id"] == sample_journal.journal_id
        assert row["name"] == sample_journal.name
        assert row["description"] == sample_journal.description
        assert row["created_at"] == sample_journal.created_at

    def test_duplicate_journal_id_raises(self, db, sample_journal):
        save_journal(sample_journal, db)

        with pytest.raises(sqlite3.IntegrityError):
            save_journal(sample_journal, db)

    def test_multiple_journals_saved(self, db):
        j1 = Journal(
            name="January",
        )
        j2 = Journal(
            name="February",
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
        credit=Decimal(0),
        category="groceries",
        tax=Decimal(0),
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

    def test_returns_all_journals_with_no_filters(self, db):
        j1 = Journal(
            name="January",
        )
        j2 = Journal(
            name="February",
        )
        save_journal(j1, db)
        save_journal(j2, db)

        results = find_journals(conn=db)

        assert len(results) == 2

    def test_filter_by_journal_id(self, db):
        j1 = Journal(
            name="January",
        )
        j2 = Journal(
            name="February",
        )
        save_journal(j1, db)
        save_journal(j2, db)

        results = find_journals(journal_id=j1.journal_id, conn=db)

        assert len(results) == 1
        assert results[0].journal_id == j1.journal_id

    def test_unknown_journal_id_returns_empty(self, db):
        assert find_journals(journal_id="nonexistent", conn=db) == []

    def test_results_ordered_by_created_at(self, db):
        j_mar = Journal(name="March", created_at="2026-03-01T00:00:00+00:00")
        j_jan = Journal(name="January", created_at="2026-01-01T00:00:00+00:00")
        j_feb = Journal(name="February", created_at="2026-02-01T00:00:00+00:00")
        save_journal(j_mar, db)
        save_journal(j_jan, db)
        save_journal(j_feb, db)

        results = find_journals(conn=db)

        assert [r.name for r in results] == ["January", "February", "March"]

    def test_entries_are_loaded(self, db, sample_journal):
        save_journal(sample_journal, db)
        entry = _make_entry("entry-1", datetime.date(2026, 1, 15), Decimal("42.50"))
        _insert_entry(db, entry, sample_journal.journal_id)

        results = find_journals(journal_id=sample_journal.journal_id, conn=db)

        assert len(results[0].entries) == 1
        e = results[0].entries[0]
        assert e.journal_entry_id == "entry-1"
        assert e.debit == Decimal("42.50")

    def test_entries_belong_to_correct_journal(self, db):
        j1 = Journal(
            name="January",
        )
        j2 = Journal(
            name="February",
        )
        save_journal(j1, db)
        save_journal(j2, db)
        _insert_entry(
            db, _make_entry("entry-j1", datetime.date(2026, 1, 10), Decimal("10.00")), j1.journal_id
        )
        _insert_entry(
            db, _make_entry("entry-j2", datetime.date(2026, 2, 10), Decimal("20.00")), j2.journal_id
        )

        results = find_journals(journal_id=j1.journal_id, conn=db)

        assert len(results[0].entries) == 1
        assert results[0].entries[0].journal_entry_id == "entry-j1"


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

        results = find_journal_entries(
            sample_journal.journal_id, date=datetime.date(2026, 1, 10), conn=db
        )

        assert len(results) == 1
        assert results[0].journal_entry_id == "entry-1"

    def test_filter_by_date_returns_empty_when_no_match(self, db, sample_journal):
        save_journal(sample_journal, db)
        _insert_entry(
            db,
            _make_entry("entry-1", datetime.date(2026, 1, 10), Decimal("10.00")),
            sample_journal.journal_id,
        )

        results = find_journal_entries(
            sample_journal.journal_id, date=datetime.date(2026, 1, 15), conn=db
        )

        assert results == []

    def test_filter_by_date_returns_multiple_entries_same_date(self, db, sample_journal):
        save_journal(sample_journal, db)
        e1 = _make_entry("entry-1", datetime.date(2026, 1, 10), Decimal("10.00"))
        e2 = _make_entry("entry-2", datetime.date(2026, 1, 10), Decimal("20.00"))
        _insert_entry(db, e1, sample_journal.journal_id)
        _insert_entry(db, e2, sample_journal.journal_id)

        results = find_journal_entries(
            sample_journal.journal_id, date=datetime.date(2026, 1, 10), conn=db
        )

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
            (
                "entry-null-recip",
                sample_journal.journal_id,
                "2026-01-10",
                "cash",
                "test",
                "5.00",
                "0",
                None,
                "0",
                None,
            ),
        )
        db.commit()

        results = find_journal_entries(sample_journal.journal_id, conn=db)

        assert results[0].recipient == RECIPIENT_SELF

    def test_entries_ordered_by_date(self, db, sample_journal):
        save_journal(sample_journal, db)
        _insert_entry(
            db,
            _make_entry("entry-3", datetime.date(2026, 1, 30), Decimal("30.00")),
            sample_journal.journal_id,
        )
        _insert_entry(
            db,
            _make_entry("entry-1", datetime.date(2026, 1, 10), Decimal("10.00")),
            sample_journal.journal_id,
        )
        _insert_entry(
            db,
            _make_entry("entry-2", datetime.date(2026, 1, 20), Decimal("20.00")),
            sample_journal.journal_id,
        )

        results = find_journal_entries(sample_journal.journal_id, conn=db)

        assert [e.journal_entry_id for e in results] == ["entry-1", "entry-2", "entry-3"]

    def test_entries_scoped_to_journal(self, db):
        j1 = Journal(
            name="January",
        )
        j2 = Journal(
            name="February",
        )
        save_journal(j1, db)
        save_journal(j2, db)
        _insert_entry(
            db, _make_entry("entry-j1", datetime.date(2026, 1, 10), Decimal("10.00")), j1.journal_id
        )
        _insert_entry(
            db, _make_entry("entry-j2", datetime.date(2026, 2, 10), Decimal("20.00")), j2.journal_id
        )

        results = find_journal_entries(j1.journal_id, conn=db)

        assert len(results) == 1
        assert results[0].journal_entry_id == "entry-j1"


class TestDeleteJournal:
    def test_deletes_journal(self, db, sample_journal):
        save_journal(sample_journal, db)

        delete_journal(sample_journal.journal_id, db)

        assert find_journals(journal_id=sample_journal.journal_id, conn=db) == []

    def test_cascades_to_entries(self, db, sample_journal):
        save_journal(sample_journal, db)
        _insert_entry(
            db,
            _make_entry("entry-1", datetime.date(2026, 1, 10), Decimal("10.00")),
            sample_journal.journal_id,
        )

        delete_journal(sample_journal.journal_id, db)

        rows = db.execute(
            "SELECT * FROM journal_entries WHERE journal_id = ?", (sample_journal.journal_id,)
        ).fetchall()
        assert rows == []

    def test_raises_when_journal_not_found(self, db):
        with pytest.raises(ValueError, match="nonexistent"):
            delete_journal("nonexistent", db)

    def test_does_not_delete_other_journals(self, db):
        j1 = Journal(
            name="January",
        )
        j2 = Journal(
            name="February",
        )
        save_journal(j1, db)
        save_journal(j2, db)

        delete_journal(j1.journal_id, db)

        remaining = find_journals(conn=db)
        assert len(remaining) == 1
        assert remaining[0].journal_id == j2.journal_id


class TestUpdateJournal:
    def test_updates_journal_metadata(self, db, sample_journal):
        save_journal(sample_journal, db)
        sample_journal.name = "Updated name"
        sample_journal.description = "Updated description"

        update_journal(sample_journal, db)

        row = db.execute(
            "SELECT * FROM journals WHERE journal_id = ?", (sample_journal.journal_id,)
        ).fetchone()
        assert row["name"] == "Updated name"
        assert row["description"] == "Updated description"

    def test_replaces_entries(self, db, sample_journal):
        save_journal(sample_journal, db)
        db.execute(
            "INSERT INTO journal_entries VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "entry-1",
                sample_journal.journal_id,
                "2026-01-10",
                "cash",
                "old",
                "10.00",
                "0",
                None,
                "0",
                "Self",
            ),
        )

        entry2 = _make_entry("entry-2", datetime.date(2026, 1, 20), Decimal("99.00"))
        sample_journal.entries = [entry2]
        update_journal(sample_journal, db)

        rows = db.execute(
            "SELECT * FROM journal_entries WHERE journal_id = ?", (sample_journal.journal_id,)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["journal_entry_id"] == "entry-2"

    def test_raises_when_journal_not_found(self, db, sample_journal):
        with pytest.raises(ValueError, match=sample_journal.journal_id):
            update_journal(sample_journal, db)

    def test_journal_not_updated_if_entries_insert_fails(self, db, sample_journal):
        save_journal(sample_journal, db)
        # pre-insert an entry in another journal to cause a PRIMARY KEY collision
        other = Journal(
            name="Other",
        )
        save_journal(other, db)
        db.execute(
            "INSERT INTO journal_entries VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "entry-collision",
                other.journal_id,
                "2026-02-01",
                "cash",
                "other",
                "5.00",
                "0",
                None,
                "0",
                "Self",
            ),
        )
        db.commit()

        # update sample_journal with a new name and an entry whose ID collides
        sample_journal.name = "Should not persist"
        collision_entry = _make_entry(
            "entry-collision", datetime.date(2026, 1, 5), Decimal("20.00")
        )
        sample_journal.entries = [collision_entry]

        with pytest.raises(sqlite3.IntegrityError):
            update_journal(sample_journal, db)

        # journal name must be unchanged
        row = db.execute(
            "SELECT name FROM journals WHERE journal_id = ?", (sample_journal.journal_id,)
        ).fetchone()
        assert row["name"] == "January journal"
