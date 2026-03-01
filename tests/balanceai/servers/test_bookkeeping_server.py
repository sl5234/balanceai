import datetime
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

# anthropic is not installed in the test environment — stub it out so that
# balanceai.services.anthropic_service can be imported and patched.
sys.modules.setdefault("anthropic", MagicMock())

from balanceai.models.account import Account, AccountType
from balanceai.models.bank import Bank
from balanceai.models.journal import (
    Journal,
    JournalAccount,
    JournalEntry,
    JournalEntryData,
    JournalEntryDataSet,
    JournalEntryInputConfig,
)
from balanceai.servers.bookkeeping_server import create_or_update_journal_entries, list_journal_entries


@pytest.fixture
def sample_account():
    return Account(id="acct-1", bank=Bank.CHASE, account_type=AccountType.DEBIT)


@pytest.fixture
def sample_entry():
    return JournalEntry(
        journal_entry_id="entry-1",
        date=datetime.date(2026, 1, 27),
        account=JournalAccount.CASH,
        description="Trader Joe's purchase",
        debit=Decimal("32.02"),
        credit=Decimal("0.00"),
    )


@pytest.fixture
def sample_entry_2():
    return JournalEntry(
        journal_entry_id="entry-2",
        date=datetime.date(2026, 1, 28),
        account=JournalAccount.CASH,
        description="Whole Foods purchase",
        debit=Decimal("54.10"),
        credit=Decimal("0.00"),
    )


@pytest.fixture
def journal_with_no_entries(sample_account):
    return Journal(
        journal_id="journal-1",
        account=sample_account,
        description="January journal",
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 1, 31),
        entries=[],
    )


@pytest.fixture
def journal_with_entries(sample_account, sample_entry, sample_entry_2):
    return Journal(
        journal_id="journal-1",
        account=sample_account,
        description="January journal",
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 1, 31),
        entries=[sample_entry, sample_entry_2],
    )


class TestListJournalEntries:
    def test_returns_empty_list_when_journal_has_no_entries(self):
        with patch("balanceai.servers.bookkeeping_server.load_journal_entries", return_value=[]):
            result = list_journal_entries("journal-1")
        assert result == []

    def test_returns_all_entries(self, sample_entry, sample_entry_2):
        with patch("balanceai.servers.bookkeeping_server.load_journal_entries", return_value=[sample_entry, sample_entry_2]):
            result = list_journal_entries("journal-1")
        assert len(result) == 2

    def test_returns_entries_in_order(self, sample_entry, sample_entry_2):
        with patch("balanceai.servers.bookkeeping_server.load_journal_entries", return_value=[sample_entry, sample_entry_2]):
            result = list_journal_entries("journal-1")
        assert result[0]["journal_entry_id"] == sample_entry.journal_entry_id
        assert result[1]["journal_entry_id"] == sample_entry_2.journal_entry_id

    def test_entries_are_returned_as_dicts(self, sample_entry, sample_entry_2):
        with patch("balanceai.servers.bookkeeping_server.load_journal_entries", return_value=[sample_entry, sample_entry_2]):
            result = list_journal_entries("journal-1")
        for entry in result:
            assert isinstance(entry, dict)

    def test_entry_dict_contains_expected_fields(self, sample_entry):
        with patch("balanceai.servers.bookkeeping_server.load_journal_entries", return_value=[sample_entry]):
            result = list_journal_entries("journal-1")
        entry = result[0]
        assert entry["journal_entry_id"] == sample_entry.journal_entry_id
        assert entry["date"] == sample_entry.date.isoformat()
        assert entry["description"] == sample_entry.description
        assert entry["debit"] == str(sample_entry.debit)
        assert entry["credit"] == str(sample_entry.credit)

    def test_entry_dict_includes_tax_field(self, sample_entry):
        with patch("balanceai.servers.bookkeeping_server.load_journal_entries", return_value=[sample_entry]):
            result = list_journal_entries("journal-1")
        for entry in result:
            assert "tax" in entry
            assert entry["tax"] == "0"

    def test_raises_value_error_when_journal_not_found(self):
        with patch("balanceai.servers.bookkeeping_server.load_journal_entries", side_effect=ValueError("journal-999")):
            with pytest.raises(ValueError, match="journal-999"):
                list_journal_entries("journal-999")

    def test_filters_entries_by_date(self, sample_entry):
        with patch("balanceai.servers.bookkeeping_server.load_journal_entries", return_value=[sample_entry]) as mock:
            result = list_journal_entries("journal-1", date=sample_entry.date)
        mock.assert_called_once_with("journal-1", date=sample_entry.date)
        assert len(result) == 1
        assert result[0]["journal_entry_id"] == sample_entry.journal_entry_id

    def test_returns_empty_list_when_no_entries_match_date(self):
        with patch("balanceai.servers.bookkeeping_server.load_journal_entries", return_value=[]):
            result = list_journal_entries("journal-1", date=datetime.date(2020, 1, 1))
        assert result == []

    def test_returns_all_entries_when_date_not_provided(self, sample_entry, sample_entry_2):
        with patch("balanceai.servers.bookkeeping_server.load_journal_entries", return_value=[sample_entry, sample_entry_2]):
            result = list_journal_entries("journal-1")
        assert len(result) == 2


# ---------------------------------------------------------------------------
# create_or_update_journal_entries
# ---------------------------------------------------------------------------


@pytest.fixture
def journal(sample_account):
    return Journal(
        journal_id="journal-1",
        account=sample_account,
        description="January journal",
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 1, 31),
        entries=[],
    )


@pytest.fixture
def input_config(tmp_path):
    # File must exist so read_bytes() succeeds; contents are irrelevant because
    # OcrUtil.executeWithAnthropic is mocked in every test.
    img = tmp_path / "receipt.jpg"
    img.write_bytes(b"fake-image-data")
    return JournalEntryInputConfig(input_local_path=img)


@pytest.fixture
def ocr_entry_data():
    return JournalEntryData(
        date=datetime.date(2026, 1, 27),
        account=JournalAccount.GENERAL,
        description="Grocery purchase at Trader Joe's",
        debit=Decimal("32.02"),
        credit=Decimal("0.00"),
    )


@pytest.fixture
def ocr_result(ocr_entry_data):
    return JournalEntryDataSet(entries=[ocr_entry_data])


class TestCreateOrUpdateJournalEntries:
    def test_raises_when_journal_not_found(self, input_config):
        with patch("balanceai.servers.bookkeeping_server.find_journal_by_id", return_value=None):
            with pytest.raises(ValueError, match="journal-999"):
                create_or_update_journal_entries("journal-999", input_config)

    def test_creates_new_entry_when_no_match(self, journal, input_config, ocr_result):
        with patch("balanceai.servers.bookkeeping_server.find_journal_by_id", return_value=journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai.servers.bookkeeping_server.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.servers.bookkeeping_server.storage_update_journal"):
                        result = create_or_update_journal_entries("journal-1", input_config)

        assert len(result["entries"]) == 1
        assert result["entries"][0]["description"] == "Grocery purchase at Trader Joe's"

    def test_new_entry_gets_fresh_id(self, journal, input_config, ocr_result):
        with patch("balanceai.servers.bookkeeping_server.find_journal_by_id", return_value=journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai.servers.bookkeeping_server.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.servers.bookkeeping_server.storage_update_journal"):
                        result = create_or_update_journal_entries("journal-1", input_config)

        entry_id = result["entries"][0]["journal_entry_id"]
        assert entry_id is not None
        assert entry_id != ""

    def test_updates_existing_entry_preserving_id(self, sample_account, input_config, ocr_result):
        existing_entry = JournalEntry(
            journal_entry_id="original-id",
            date=datetime.date(2026, 1, 27),
            account=JournalAccount.GENERAL,
            description="Old description",
            debit=Decimal("30.00"),
            credit=Decimal("0.00"),
        )
        journal = Journal(
            journal_id="journal-1",
            account=sample_account,
            description="January journal",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
            entries=[existing_entry],
        )

        with patch("balanceai.servers.bookkeeping_server.find_journal_by_id", return_value=journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai.servers.bookkeeping_server.finder_find_journal_entry", return_value=existing_entry):
                    with patch("balanceai.servers.bookkeeping_server.storage_update_journal"):
                        result = create_or_update_journal_entries("journal-1", input_config)

        assert len(result["entries"]) == 1
        assert result["entries"][0]["journal_entry_id"] == "original-id"
        assert result["entries"][0]["description"] == "Grocery purchase at Trader Joe's"
        assert result["entries"][0]["debit"] == "32.02"

    def test_adds_multiple_entries_from_ocr(self, journal, input_config):
        # Double-entry: one debit line and one credit line from the same receipt
        double_entry_result = JournalEntryDataSet(entries=[
            JournalEntryData(
                date=datetime.date(2026, 1, 27),
                account=JournalAccount.GENERAL,
                description="Grocery purchase at Trader Joe's",
                debit=Decimal("32.02"),
                credit=Decimal("0.00"),
            ),
            JournalEntryData(
                date=datetime.date(2026, 1, 27),
                account=JournalAccount.CASH,
                description="Payment via Visa",
                debit=Decimal("0.00"),
                credit=Decimal("32.02"),
            ),
        ])

        with patch("balanceai.servers.bookkeeping_server.find_journal_by_id", return_value=journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=double_entry_result):
                with patch("balanceai.servers.bookkeeping_server.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.servers.bookkeeping_server.storage_update_journal"):
                        result = create_or_update_journal_entries("journal-1", input_config)

        assert len(result["entries"]) == 2

    def test_no_entries_from_ocr_leaves_journal_unchanged(self, journal, input_config):
        empty_ocr_result = JournalEntryDataSet(entries=[])

        with patch("balanceai.servers.bookkeeping_server.find_journal_by_id", return_value=journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=empty_ocr_result):
                with patch("balanceai.servers.bookkeeping_server.storage_update_journal"):
                    result = create_or_update_journal_entries("journal-1", input_config)

        assert result["entries"] == []

    def test_storage_update_called_once(self, journal, input_config, ocr_result):
        with patch("balanceai.servers.bookkeeping_server.find_journal_by_id", return_value=journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai.servers.bookkeeping_server.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.servers.bookkeeping_server.storage_update_journal") as mock_save:
                        create_or_update_journal_entries("journal-1", input_config)

        mock_save.assert_called_once_with(journal)

    def test_returns_journal_as_dict(self, journal, input_config, ocr_result):
        with patch("balanceai.servers.bookkeeping_server.find_journal_by_id", return_value=journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai.servers.bookkeeping_server.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.servers.bookkeeping_server.storage_update_journal"):
                        result = create_or_update_journal_entries("journal-1", input_config)

        assert isinstance(result, dict)
        assert "journal_id" in result
        assert "entries" in result

    def test_mixed_new_and_updated_entries(self, sample_account, input_config):
        # The journal already has a GENERAL entry. OCR returns two entries:
        # one GENERAL (matches the existing entry → update, preserve ID) and
        # one CASH (no match → create, gets a new ID).
        existing_entry = JournalEntry(
            journal_entry_id="existing-id",
            date=datetime.date(2026, 1, 27),
            account=JournalAccount.GENERAL,
            description="Old grocery description",
            debit=Decimal("30.00"),
            credit=Decimal("0.00"),
        )
        journal = Journal(
            journal_id="journal-1",
            account=sample_account,
            description="January journal",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
            entries=[existing_entry],
        )
        ocr_result = JournalEntryDataSet(entries=[
            JournalEntryData(
                date=datetime.date(2026, 1, 27),
                account=JournalAccount.GENERAL,
                description="Grocery purchase at Trader Joe's",
                debit=Decimal("32.02"),
                credit=Decimal("0.00"),
            ),
            JournalEntryData(
                date=datetime.date(2026, 1, 27),
                account=JournalAccount.CASH,
                description="Payment via Visa",
                debit=Decimal("0.00"),
                credit=Decimal("32.02"),
            ),
        ])

        def fake_finder(journal_id, entry):
            # Only the GENERAL entry matches the pre-existing journal entry
            return existing_entry if entry.account == JournalAccount.GENERAL else None

        with patch("balanceai.servers.bookkeeping_server.find_journal_by_id", return_value=journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai.servers.bookkeeping_server.finder_find_journal_entry", side_effect=fake_finder):
                    with patch("balanceai.servers.bookkeeping_server.storage_update_journal"):
                        result = create_or_update_journal_entries("journal-1", input_config)

        assert len(result["entries"]) == 2
        ids = {e["journal_entry_id"] for e in result["entries"]}
        assert "existing-id" in ids
