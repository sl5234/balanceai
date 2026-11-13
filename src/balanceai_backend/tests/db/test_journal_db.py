import datetime
import sqlite3
from decimal import Decimal

import pytest
from balanceai_backend.db.bank_account_db import find_bank_accounts, upsert_bank_account
from balanceai_backend.db.connection import create_schema
from balanceai_backend.db.journal_db import (
    add_journal_entries,
    add_journal_entry,
    delete_journal,
    delete_journal_entries,
    delete_journal_entries_for_bank_account,
    delete_journal_entries_for_transaction,
    delete_journal_entry,
    find_booked_transactions,
    find_journal_lines,
    find_journals,
    is_account_in_journal,
    save_journal,
    update_journal,
)
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.journal import Journal, JournalAccount, JournalLine


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


def _make_entry(line_id: str, date: datetime.date, amount: Decimal) -> JournalLine:
    return JournalLine(
        journal_line_id=line_id,
        date=date,
        account=JournalAccount.CASH,
        description="Test transaction",
        debit=amount,
        credit=Decimal(0),
        category="groceries",
        tax=Decimal(0),
        counterparty="Self",
    )


def _insert_entry(db, entry: JournalLine, journal_id: str) -> None:
    db.execute(
        "INSERT INTO journal_lines (journal_line_id, journal_id, date, account, description, debit, credit, category, tax, counterparty, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')",
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
            entry.counterparty,
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

        assert len(results[0].lines) == 1
        e = results[0].lines[0]
        assert e.journal_line_id == "entry-1"
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

        assert len(results[0].lines) == 1
        assert results[0].lines[0].journal_line_id == "entry-j1"


class TestFindJournalEntries:
    def test_raises_when_journal_not_found(self, db):
        with pytest.raises(ValueError, match="nonexistent"):
            find_journal_lines("nonexistent", conn=db)

    def test_returns_empty_list_when_no_entries(self, db, sample_journal):
        save_journal(sample_journal, db)

        assert find_journal_lines(sample_journal.journal_id, conn=db) == []

    def test_returns_all_entries_when_no_date_filter(self, db, sample_journal):
        save_journal(sample_journal, db)
        e1 = _make_entry("entry-1", datetime.date(2026, 1, 10), Decimal("10.00"))
        e2 = _make_entry("entry-2", datetime.date(2026, 1, 20), Decimal("20.00"))
        _insert_entry(db, e1, sample_journal.journal_id)
        _insert_entry(db, e2, sample_journal.journal_id)

        results = find_journal_lines(sample_journal.journal_id, conn=db)

        assert {e.journal_line_id for e in results} == {"entry-1", "entry-2"}

    def test_filter_by_date_returns_matching_entries(self, db, sample_journal):
        save_journal(sample_journal, db)
        e1 = _make_entry("entry-1", datetime.date(2026, 1, 10), Decimal("10.00"))
        e2 = _make_entry("entry-2", datetime.date(2026, 1, 20), Decimal("20.00"))
        _insert_entry(db, e1, sample_journal.journal_id)
        _insert_entry(db, e2, sample_journal.journal_id)

        results = find_journal_lines(
            sample_journal.journal_id, date=datetime.date(2026, 1, 10), conn=db
        )

        assert len(results) == 1
        assert results[0].journal_line_id == "entry-1"

    def test_filter_by_date_returns_empty_when_no_match(self, db, sample_journal):
        save_journal(sample_journal, db)
        _insert_entry(
            db,
            _make_entry("entry-1", datetime.date(2026, 1, 10), Decimal("10.00")),
            sample_journal.journal_id,
        )

        results = find_journal_lines(
            sample_journal.journal_id, date=datetime.date(2026, 1, 15), conn=db
        )

        assert results == []

    def test_filter_by_date_returns_multiple_entries_same_date(self, db, sample_journal):
        save_journal(sample_journal, db)
        e1 = _make_entry("entry-1", datetime.date(2026, 1, 10), Decimal("10.00"))
        e2 = _make_entry("entry-2", datetime.date(2026, 1, 10), Decimal("20.00"))
        _insert_entry(db, e1, sample_journal.journal_id)
        _insert_entry(db, e2, sample_journal.journal_id)

        results = find_journal_lines(
            sample_journal.journal_id, date=datetime.date(2026, 1, 10), conn=db
        )

        assert {e.journal_line_id for e in results} == {"entry-1", "entry-2"}

    def test_entry_fields_are_correctly_mapped(self, db, sample_journal):
        save_journal(sample_journal, db)
        entry = JournalLine(
            journal_line_id="entry-full",
            date=datetime.date(2026, 1, 15),
            account=JournalAccount.CASH,
            description="Full field test",
            debit=Decimal("42.50"),
            credit=Decimal("0.00"),
            category="groceries",
            tax=Decimal("3.50"),
            counterparty="Jane",
        )
        _insert_entry(db, entry, sample_journal.journal_id)

        results = find_journal_lines(sample_journal.journal_id, conn=db)

        assert len(results) == 1
        e = results[0]
        assert e.journal_line_id == "entry-full"
        assert e.date == datetime.date(2026, 1, 15)
        assert e.account == JournalAccount.CASH
        assert e.description == "Full field test"
        assert e.debit == Decimal("42.50")
        assert e.credit == Decimal("0.00")
        assert e.category == "groceries"
        assert e.tax == Decimal("3.50")
        assert e.counterparty == "Jane"

    def test_null_counterparty_defaults_to_self(self, db, sample_journal):
        from balanceai_backend.models.journal import COUNTERPARTY_SELF

        save_journal(sample_journal, db)
        db.execute(
            "INSERT INTO journal_lines (journal_line_id, journal_id, date, account, description, debit, credit, category, tax, counterparty, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')",
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

        results = find_journal_lines(sample_journal.journal_id, conn=db)

        assert results[0].counterparty == COUNTERPARTY_SELF

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

        results = find_journal_lines(sample_journal.journal_id, conn=db)

        assert [e.journal_line_id for e in results] == ["entry-1", "entry-2", "entry-3"]

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

        results = find_journal_lines(j1.journal_id, conn=db)

        assert len(results) == 1
        assert results[0].journal_line_id == "entry-j1"


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
            "SELECT * FROM journal_lines WHERE journal_id = ?", (sample_journal.journal_id,)
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
            "INSERT INTO journal_lines (journal_line_id, journal_id, date, account, description, debit, credit, category, tax, counterparty, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')",
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
        sample_journal.lines = [entry2]
        update_journal(sample_journal, db)

        rows = db.execute(
            "SELECT * FROM journal_lines WHERE journal_id = ?", (sample_journal.journal_id,)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["journal_line_id"] == "entry-2"

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
            "INSERT INTO journal_lines (journal_line_id, journal_id, date, account, description, debit, credit, category, tax, counterparty, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')",
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
        sample_journal.lines = [collision_entry]

        with pytest.raises(sqlite3.IntegrityError):
            update_journal(sample_journal, db)

        # journal name must be unchanged
        row = db.execute(
            "SELECT name FROM journals WHERE journal_id = ?", (sample_journal.journal_id,)
        ).fetchone()
        assert row["name"] == "January journal"


CHECKING = "test_bank:checking:0000"
SAVINGS = "test_bank:savings:1111"
CARD = "test_bank:credit_card:2222"


@pytest.fixture
def bank_accounts(db):
    for account_id, account_type in (
        (CHECKING, BankAccountType.CHECKING),
        (SAVINGS, BankAccountType.SAVINGS),
        (CARD, BankAccountType.CREDIT_CARD),
    ):
        upsert_bank_account(
            BankAccount(
                id=account_id,
                institution_name="Test Bank",
                account_type=account_type,
                last4=account_id[-4:],
            ),
            conn=db,
        )


def _bank_account_ids(db, journal: Journal) -> list[str]:
    [found] = find_journals(journal_id=journal.journal_id, conn=db)
    return found.bank_account_ids


class TestJournalBankAccounts:
    def test_saved_and_loaded(self, db, bank_accounts):
        journal = Journal(name="Personal", bank_account_ids=[SAVINGS, CHECKING])

        save_journal(journal, db)

        assert _bank_account_ids(db, journal) == [CHECKING, SAVINGS]

    def test_duplicates_collapsed(self, db, bank_accounts):
        journal = Journal(name="Personal", bank_account_ids=[CHECKING, CHECKING])

        save_journal(journal, db)

        assert _bank_account_ids(db, journal) == [CHECKING]

    def test_unknown_account_raises_and_saves_nothing(self, db, bank_accounts):
        journal = Journal(name="Personal", bank_account_ids=[CHECKING, "no_such_account"])

        with pytest.raises(ValueError, match="no_such_account not found"):
            save_journal(journal, db)

        assert find_journals(conn=db) == []

    def test_account_in_another_journal_raises(self, db, bank_accounts):
        save_journal(Journal(name="Personal", bank_account_ids=[CHECKING]), db)
        llc = Journal(name="My LLC", bank_account_ids=[CHECKING])

        with pytest.raises(ValueError, match="already in journal 'Personal'"):
            save_journal(llc, db)

        assert [j.name for j in find_journals(conn=db)] == ["Personal"]

    def test_update_replaces_the_list(self, db, bank_accounts):
        journal = Journal(name="Personal", bank_account_ids=[CHECKING, SAVINGS])
        save_journal(journal, db)

        journal.bank_account_ids = [SAVINGS, CARD]
        update_journal(journal, db)

        assert _bank_account_ids(db, journal) == [CARD, SAVINGS]

    def test_update_with_empty_list_removes_all(self, db, bank_accounts):
        journal = Journal(name="Personal", bank_account_ids=[CHECKING, SAVINGS])
        save_journal(journal, db)

        journal.bank_account_ids = []
        update_journal(journal, db)

        assert _bank_account_ids(db, journal) == []

    def test_keeping_own_accounts_is_fine(self, db, bank_accounts):
        journal = Journal(name="Personal", bank_account_ids=[CHECKING])
        save_journal(journal, db)

        journal.name = "Home"
        update_journal(journal, db)

        assert _bank_account_ids(db, journal) == [CHECKING]

    def test_failed_update_changes_nothing(self, db, bank_accounts):
        journal = Journal(name="Personal", bank_account_ids=[CHECKING])
        save_journal(journal, db)

        journal.name = "Should not persist"
        journal.bank_account_ids = [SAVINGS, "no_such_account"]
        with pytest.raises(ValueError):
            update_journal(journal, db)

        [found] = find_journals(journal_id=journal.journal_id, conn=db)
        assert (found.name, found.bank_account_ids) == ("Personal", [CHECKING])

    def test_deleting_journal_frees_its_accounts(self, db, bank_accounts):
        personal = Journal(name="Personal", bank_account_ids=[CHECKING])
        save_journal(personal, db)

        delete_journal(personal.journal_id, db)
        llc = Journal(name="My LLC", bank_account_ids=[CHECKING])
        save_journal(llc, db)

        assert _bank_account_ids(db, llc) == [CHECKING]
        assert CHECKING in {a.id for a in find_bank_accounts(conn=db)}


class TestEntrySource:
    def test_entry_source_transaction_and_bank_account_ids_round_trip(self, db, sample_journal):
        save_journal(sample_journal, db)
        entry = _make_entry("entry-1", datetime.date(2026, 9, 8), Decimal("4.33"))
        entry.journal_entry_id = "e-1"
        entry.transaction_id = "txn-1"
        entry.bank_account_id = CHECKING
        sample_journal.lines = [entry]

        update_journal(sample_journal, db)

        [found] = find_journal_lines(sample_journal.journal_id, conn=db)
        assert (found.journal_entry_id, found.transaction_id, found.bank_account_id) == (
            "e-1",
            "txn-1",
            CHECKING,
        )

    def test_entries_without_a_source_read_as_none(self, db, sample_journal):
        save_journal(sample_journal, db)
        sample_journal.lines = [_make_entry("entry-1", datetime.date(2026, 9, 8), Decimal("4.33"))]

        update_journal(sample_journal, db)

        [found] = find_journal_lines(sample_journal.journal_id, conn=db)
        assert (found.journal_entry_id, found.transaction_id, found.bank_account_id) == (
            None,
            None,
            None,
        )


def _lines(journal_entry_id: str, *transaction_ids: str | None) -> list[JournalLine]:
    """One entry's lines, one per source transaction id."""
    lines = []
    for n, transaction_id in enumerate(transaction_ids):
        line = _make_entry(f"{journal_entry_id}-{n}", datetime.date(2026, 9, 8), Decimal("4.33"))
        line.journal_entry_id = journal_entry_id
        line.transaction_id = transaction_id
        lines.append(line)
    return lines


def _entry_ids(db, journal: Journal) -> list[str | None]:
    return sorted(
        {e.journal_entry_id for e in find_journal_lines(journal.journal_id, conn=db)},
        key=lambda e: e or "",
    )


class TestBookedEntries:
    def test_add_journal_entry_round_trips(self, db, sample_journal):
        save_journal(sample_journal, db)

        with db:
            add_journal_entry(sample_journal.journal_id, _lines("e-1", "txn-1", "txn-1"), db)

        found = find_journal_lines(sample_journal.journal_id, conn=db)
        assert sorted(e.journal_line_id for e in found) == ["e-1-0", "e-1-1"]
        assert {e.journal_entry_id for e in found} == {"e-1"}

    def test_add_journal_entries_adds_each(self, db, sample_journal):
        save_journal(sample_journal, db)

        with db:
            add_journal_entries(
                sample_journal.journal_id,
                [_lines("e-1", "txn-1", "txn-1"), _lines("e-2", "txn-2", "txn-2")],
                db,
            )

        assert _entry_ids(db, sample_journal) == ["e-1", "e-2"]

    def test_find_booked_transactions(self, db, sample_journal):
        other = Journal(name="Other")
        save_journal(sample_journal, db)
        save_journal(other, db)
        with db:
            add_journal_entries(
                sample_journal.journal_id,
                [
                    _lines("e-1", "txn-1", "txn-1"),
                    _lines("match", "out", "in"),
                    _lines("manual", None, None),
                ],
                db,
            )
            add_journal_entry(other.journal_id, _lines("e-9", "txn-9", "txn-9"), db)

        assert find_booked_transactions(sample_journal.journal_id, db) == {
            "txn-1": "e-1",
            "out": "match",
            "in": "match",
        }

    def test_delete_journal_entry_removes_only_that_entry(self, db, sample_journal):
        save_journal(sample_journal, db)
        with db:
            add_journal_entries(
                sample_journal.journal_id,
                [_lines("e-1", "txn-1", "txn-1"), _lines("e-2", "txn-2", "txn-2")],
                db,
            )

        with db:
            delete_journal_entry("e-1", db)

        assert _entry_ids(db, sample_journal) == ["e-2"]

    def test_delete_journal_entries_removes_each(self, db, sample_journal):
        save_journal(sample_journal, db)
        with db:
            add_journal_entries(
                sample_journal.journal_id,
                [
                    _lines("e-1", "txn-1", "txn-1"),
                    _lines("e-2", "txn-2", "txn-2"),
                    _lines("e-3", "txn-3", "txn-3"),
                ],
                db,
            )

        with db:
            delete_journal_entries(["e-1", "e-3"], db)

        assert _entry_ids(db, sample_journal) == ["e-2"]

    def test_deleting_for_a_source_transaction_removes_the_whole_match(self, db, sample_journal):
        save_journal(sample_journal, db)
        with db:
            add_journal_entries(
                sample_journal.journal_id,
                [_lines("match", "out", "in"), _lines("e-2", "txn-2", "txn-2")],
                db,
            )

        with db:
            delete_journal_entries_for_transaction("in", db)

        assert _entry_ids(db, sample_journal) == ["e-2"]


def _booked_on(journal_entry_id: str, bank_account_id: str) -> list[JournalLine]:
    """An entry whose bank-side line is on bank_account_id; the counter line has none."""
    bank_side, counter = _lines(journal_entry_id, journal_entry_id, journal_entry_id)
    bank_side.bank_account_id = bank_account_id
    return [bank_side, counter]


class TestRemovingBankAccountsDeletesTheirEntries:
    @pytest.fixture
    def personal(self, db, bank_accounts):
        journal = Journal(name="Personal", bank_account_ids=[CHECKING, SAVINGS])
        save_journal(journal, db)
        with db:
            add_journal_entries(
                journal.journal_id,
                [
                    _booked_on("on-checking", CHECKING),
                    _booked_on("on-savings", SAVINGS),
                    _lines("manual", None, None),
                ],
                db,
            )
        return journal

    @staticmethod
    def _set_bank_accounts(db, journal: Journal, bank_account_ids: list[str]) -> None:
        [found] = find_journals(journal_id=journal.journal_id, conn=db)
        found.bank_account_ids = bank_account_ids
        update_journal(found, db)

    def test_deleting_for_a_bank_account_removes_its_whole_entries(self, db, personal):
        with db:
            delete_journal_entries_for_bank_account(personal.journal_id, CHECKING, db)

        assert _entry_ids(db, personal) == ["manual", "on-savings"]

    def test_removed_accounts_entries_go_others_stay(self, db, personal):
        self._set_bank_accounts(db, personal, [SAVINGS])

        assert _entry_ids(db, personal) == ["manual", "on-savings"]

    def test_removing_all_keeps_only_manual_entries(self, db, personal):
        self._set_bank_accounts(db, personal, [])

        assert _entry_ids(db, personal) == ["manual"]

    def test_unchanged_accounts_keep_every_entry(self, db, personal):
        self._set_bank_accounts(db, personal, [CHECKING, SAVINGS])

        assert _entry_ids(db, personal) == ["manual", "on-checking", "on-savings"]


class TestFindJournalsByBankAccount:
    @pytest.fixture
    def journal_with_account(self, db):
        upsert_bank_account(
            BankAccount(
                id="test_bank:checking:0000",
                institution_name="Test Bank",
                account_type=BankAccountType.CHECKING,
                last4="0000",
            ),
            conn=db,
        )
        journal = Journal(
            journal_id="j1", name="Personal", lines=[], bank_account_ids=["test_bank:checking:0000"]
        )
        save_journal(journal, conn=db)
        save_journal(Journal(journal_id="j2", name="My LLC", lines=[]), conn=db)

    def test_finds_the_journal_holding_the_account(self, db, journal_with_account):
        [journal] = find_journals(bank_account_id="test_bank:checking:0000", conn=db)
        assert journal.journal_id == "j1"

    def test_account_in_no_journal(self, db, journal_with_account):
        assert find_journals(bank_account_id="other:checking:1111", conn=db) == []

    def test_is_account_in_journal(self, db, journal_with_account):
        assert is_account_in_journal("test_bank:checking:0000", "j1", conn=db)
        assert not is_account_in_journal("test_bank:checking:0000", "j2", conn=db)
