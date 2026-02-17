import datetime
import json
from decimal import Decimal
from unittest.mock import patch

import pytest

from balanceai.journals.storage import (
    DATA_DIR,
    _save_all_journals,
    load_journals,
    save_journal,
    update_journal,
)
from balanceai.models.account import Account, AccountType
from balanceai.models.bank import Bank
from balanceai.models.journal import Journal, JournalAccount, JournalEntry


@pytest.fixture
def sample_account():
    return Account(id="acct-1", bank=Bank.CHASE, account_type=AccountType.DEBIT)


@pytest.fixture
def sample_account_2():
    return Account(id="acct-2", bank=Bank.MARCUS, account_type=AccountType.SAVING)


@pytest.fixture
def sample_entry():
    return JournalEntry(
        journal_entry_id="j1",
        date=datetime.date(2026, 1, 15),
        account=JournalAccount.EQUIPMENT,
        description="Office supplies",
        debit=Decimal("50.00"),
        credit=Decimal("0.00"),
    )


@pytest.fixture
def sample_journal(sample_account, sample_entry):
    return Journal(
        account=sample_account,
        description="January journal",
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 1, 31),
        entries=[sample_entry],
    )


@pytest.fixture
def sample_journal_2(sample_account_2):
    return Journal(
        account=sample_account_2,
        description="February journal",
        start_date=datetime.date(2026, 2, 1),
        end_date=datetime.date(2026, 2, 28),
        entries=[],
    )


@pytest.fixture(autouse=True)
def use_tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("balanceai.journals.storage.DATA_DIR", tmp_path)


# ---------------------------------------------------------------------------
# load_journals
# ---------------------------------------------------------------------------


class TestLoadJournals:
    def test_returns_empty_list_when_file_does_not_exist(self):
        assert load_journals() == []

    def test_returns_empty_list_when_file_is_empty(self, tmp_path):
        (tmp_path / "journals.jsonl").write_text("")
        with patch("balanceai.journals.storage.DATA_DIR", tmp_path):
            assert load_journals() == []

    def test_loads_multiple_journals(self, sample_journal, sample_journal_2):
        save_journal(sample_journal)
        save_journal(sample_journal_2)

        loaded = load_journals()

        assert len(loaded) == 2
        assert loaded[0].description == "January journal"
        assert loaded[1].description == "February journal"

    def test_skips_blank_lines(self, tmp_path, sample_journal):
        line = json.dumps(sample_journal.to_dict())
        (tmp_path / "journals.jsonl").write_text(f"{line}\n\n\n{line}\n")
        with patch("balanceai.journals.storage.DATA_DIR", tmp_path):
            assert len(load_journals()) == 2

    def test_round_trip_preserves_entries(self, sample_journal, sample_entry):
        save_journal(sample_journal)

        loaded = load_journals()[0]
        entry = loaded.entries[0]

        assert entry.journal_entry_id == sample_entry.journal_entry_id
        assert entry.date == sample_entry.date
        assert entry.account == sample_entry.account
        assert entry.description == sample_entry.description
        assert entry.debit == sample_entry.debit
        assert entry.credit == sample_entry.credit


# ---------------------------------------------------------------------------
# save_journal
# ---------------------------------------------------------------------------


class TestSaveJournal:
    def test_creates_file_when_it_does_not_exist(self, tmp_path, sample_journal):
        save_journal(sample_journal)

        path = tmp_path / "journals.jsonl"
        assert path.exists()
        lines = [l for l in path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1

    def test_appends_without_overwriting(self, sample_journal, sample_journal_2):
        save_journal(sample_journal)
        save_journal(sample_journal_2)

        loaded = load_journals()
        assert len(loaded) == 2
        assert loaded[0].description == "January journal"
        assert loaded[1].description == "February journal"

    def test_round_trip_save_then_load(self, sample_journal):
        save_journal(sample_journal)
        loaded = load_journals()

        assert len(loaded) == 1
        j = loaded[0]
        assert j.account.id == sample_journal.account.id
        assert j.description == sample_journal.description
        assert j.start_date == sample_journal.start_date
        assert j.end_date == sample_journal.end_date


# ---------------------------------------------------------------------------
# _save_all_journals
# ---------------------------------------------------------------------------


class TestSaveAllJournals:
    def test_overwrites_file_with_given_journals(self, sample_journal, sample_journal_2):
        save_journal(sample_journal)
        _save_all_journals([sample_journal_2])

        loaded = load_journals()
        assert len(loaded) == 1
        assert loaded[0].description == "February journal"

    def test_writes_empty_file_for_empty_list(self, tmp_path, sample_journal):
        save_journal(sample_journal)
        _save_all_journals([])

        assert (tmp_path / "journals.jsonl").read_text() == ""

    def test_replaces_previous_contents(self, sample_journal, sample_journal_2):
        save_journal(sample_journal)
        save_journal(sample_journal_2)

        _save_all_journals([sample_journal])
        loaded = load_journals()

        assert len(loaded) == 1
        assert loaded[0].description == "January journal"


# ---------------------------------------------------------------------------
# update_journal
# ---------------------------------------------------------------------------


class TestUpdateJournal:
    def test_updates_journal(self, sample_journal):
        save_journal(sample_journal)
        sample_journal.description = "Updated"
        update_journal(sample_journal)

        loaded = load_journals()[0]
        assert loaded.description == "Updated"

    def test_raises_when_not_found(self, sample_journal):
        save_journal(sample_journal)
        not_found = Journal(
            account=sample_journal.account,
            description="Ghost",
            start_date=sample_journal.start_date,
            end_date=sample_journal.end_date,
            journal_id="nonexistent",
        )
        with pytest.raises(ValueError):
            update_journal(not_found)

    def test_updates_multiple_fields(self, sample_journal):
        save_journal(sample_journal)
        new_end = datetime.date(2026, 3, 31)
        sample_journal.description = "Updated"
        sample_journal.end_date = new_end
        update_journal(sample_journal)

        loaded = load_journals()[0]
        assert loaded.description == "Updated"
        assert loaded.end_date == new_end

    def test_leaves_other_fields_unchanged(self, sample_journal):
        save_journal(sample_journal)
        sample_journal.description = "Updated"
        update_journal(sample_journal)

        loaded = load_journals()[0]
        assert loaded.start_date == datetime.date(2026, 1, 1)
        assert loaded.end_date == datetime.date(2026, 1, 31)

    def test_persists_update_to_disk(self, sample_journal):
        save_journal(sample_journal)
        sample_journal.description = "Persisted"
        update_journal(sample_journal)

        loaded = load_journals()[0]
        assert loaded.description == "Persisted"

    def test_updates_correct_journal_among_multiple(self, sample_journal, sample_journal_2):
        save_journal(sample_journal)
        save_journal(sample_journal_2)
        sample_journal_2.description = "Updated second"
        update_journal(sample_journal_2)

        loaded = load_journals()
        assert loaded[0].description == "January journal"
        assert loaded[1].description == "Updated second"
