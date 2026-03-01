import datetime
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

sys.modules.setdefault("anthropic", MagicMock())

from balanceai.helpers.journal_entry import (
    handle_create_or_update_journal_entries_for_receipt,
    handle_create_or_update_journal_entries_for_transactions,
)
from balanceai.models.account import Account, AccountType
from balanceai.models.bank import Bank
from balanceai.models.journal import (
    Journal,
    JournalAccount,
    JournalEntry,
    JournalEntryData,
    JournalEntryDataSet,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_account():
    return Account(id="acct-1", bank=Bank.CHASE, account_type=AccountType.DEBIT)


@pytest.fixture
def empty_journal(sample_account):
    return Journal(
        journal_id="journal-1",
        account=sample_account,
        description="January journal",
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 1, 31),
        entries=[],
    )


@pytest.fixture
def entry_data():
    return JournalEntryData(
        date=datetime.date(2026, 1, 27),
        account=JournalAccount.GENERAL,
        description="Grocery purchase at Trader Joe's",
        debit=Decimal("32.02"),
        credit=Decimal("0.00"),
    )


@pytest.fixture
def existing_entry():
    return JournalEntry(
        journal_entry_id="original-id",
        date=datetime.date(2026, 1, 27),
        account=JournalAccount.GENERAL,
        description="Old description",
        debit=Decimal("30.00"),
        credit=Decimal("0.00"),
    )


# ---------------------------------------------------------------------------
# handle_create_or_update_journal_entries_for_receipt
# ---------------------------------------------------------------------------


@pytest.fixture
def receipt_path(tmp_path):
    img = tmp_path / "receipt.jpg"
    img.write_bytes(b"fake-image-data")
    return img


@pytest.fixture
def ocr_result(entry_data):
    return JournalEntryDataSet(entries=[entry_data])


class TestHandleCreateOrUpdateJournalEntriesForReceipt:
    def test_raises_when_journal_not_found(self, receipt_path):
        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=None):
            with pytest.raises(ValueError, match="journal-999"):
                handle_create_or_update_journal_entries_for_receipt("journal-999", receipt_path)

    def test_creates_new_entry_when_no_match(self, empty_journal, receipt_path, ocr_result):
        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai.helpers.journal_entry.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry.storage_update_journal"):
                        result = handle_create_or_update_journal_entries_for_receipt("journal-1", receipt_path)

        assert len(result["entries"]) == 1
        assert result["entries"][0]["description"] == "Grocery purchase at Trader Joe's"

    def test_new_entry_gets_fresh_id(self, empty_journal, receipt_path, ocr_result):
        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai.helpers.journal_entry.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry.storage_update_journal"):
                        result = handle_create_or_update_journal_entries_for_receipt("journal-1", receipt_path)

        entry_id = result["entries"][0]["journal_entry_id"]
        assert entry_id is not None
        assert entry_id != ""

    def test_updates_existing_entry_preserving_id(self, sample_account, receipt_path, ocr_result, existing_entry):
        journal = Journal(
            journal_id="journal-1",
            account=sample_account,
            description="January journal",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
            entries=[existing_entry],
        )

        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai.helpers.journal_entry.finder_find_journal_entry", return_value=existing_entry):
                    with patch("balanceai.helpers.journal_entry.storage_update_journal"):
                        result = handle_create_or_update_journal_entries_for_receipt("journal-1", receipt_path)

        assert len(result["entries"]) == 1
        assert result["entries"][0]["journal_entry_id"] == "original-id"
        assert result["entries"][0]["description"] == "Grocery purchase at Trader Joe's"
        assert result["entries"][0]["debit"] == "32.02"

    def test_adds_multiple_entries(self, empty_journal, receipt_path):
        double_entry_result = JournalEntryDataSet(entries=[
            JournalEntryData(
                date=datetime.date(2026, 1, 27),
                account=JournalAccount.EXPENSE,
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

        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=double_entry_result):
                with patch("balanceai.helpers.journal_entry.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry.storage_update_journal"):
                        result = handle_create_or_update_journal_entries_for_receipt("journal-1", receipt_path)

        assert len(result["entries"]) == 2

    def test_no_entries_from_ocr_leaves_journal_unchanged(self, empty_journal, receipt_path):
        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=JournalEntryDataSet(entries=[])):
                with patch("balanceai.helpers.journal_entry.storage_update_journal"):
                    result = handle_create_or_update_journal_entries_for_receipt("journal-1", receipt_path)

        assert result["entries"] == []

    def test_storage_update_called_once(self, empty_journal, receipt_path, ocr_result):
        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai.helpers.journal_entry.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry.storage_update_journal") as mock_save:
                        handle_create_or_update_journal_entries_for_receipt("journal-1", receipt_path)

        mock_save.assert_called_once_with(empty_journal)

    def test_returns_journal_as_dict(self, empty_journal, receipt_path, ocr_result):
        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai.helpers.journal_entry.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry.storage_update_journal"):
                        result = handle_create_or_update_journal_entries_for_receipt("journal-1", receipt_path)

        assert isinstance(result, dict)
        assert "journal_id" in result
        assert "entries" in result

    def test_passes_file_bytes_and_mime_type_to_ocr(self, empty_journal, receipt_path, ocr_result):
        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result) as mock_ocr:
                with patch("balanceai.helpers.journal_entry.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry.storage_update_journal"):
                        handle_create_or_update_journal_entries_for_receipt("journal-1", receipt_path)

        mock_ocr.assert_called_once()
        call_kwargs = mock_ocr.call_args.kwargs
        assert call_kwargs["content"] == b"fake-image-data"
        assert call_kwargs["mime_type"] == "image/jpeg"
        assert call_kwargs["output_format"] == JournalEntryDataSet


# ---------------------------------------------------------------------------
# handle_create_or_update_journal_entries_for_transactions
# ---------------------------------------------------------------------------


@pytest.fixture
def transactions():
    return {"added": [{"transaction_id": "txn-1"}], "modified": [], "removed": []}


class TestHandleCreateOrUpdateJournalEntriesForTransactions:
    def test_raises_when_journal_not_found(self, transactions):
        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=None):
            with pytest.raises(ValueError, match="journal-999"):
                handle_create_or_update_journal_entries_for_transactions("journal-999", transactions)

    def test_creates_new_entry_for_added_transaction(self, empty_journal, transactions, entry_data):
        grouped = {"upsert": [entry_data], "remove": []}

        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai.helpers.journal_entry.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry.storage_update_journal"):
                        result = handle_create_or_update_journal_entries_for_transactions("journal-1", transactions)

        assert len(result["entries"]) == 1
        assert result["entries"][0]["description"] == "Grocery purchase at Trader Joe's"

    def test_updates_existing_entry_preserving_id(self, sample_account, transactions, entry_data, existing_entry):
        journal = Journal(
            journal_id="journal-1",
            account=sample_account,
            description="January journal",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
            entries=[existing_entry],
        )
        grouped = {"upsert": [entry_data], "remove": []}

        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=journal):
            with patch("balanceai.helpers.journal_entry.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai.helpers.journal_entry.finder_find_journal_entry", return_value=existing_entry):
                    with patch("balanceai.helpers.journal_entry.storage_update_journal"):
                        result = handle_create_or_update_journal_entries_for_transactions("journal-1", transactions)

        assert len(result["entries"]) == 1
        assert result["entries"][0]["journal_entry_id"] == "original-id"
        assert result["entries"][0]["description"] == "Grocery purchase at Trader Joe's"
        assert result["entries"][0]["debit"] == "32.02"

    def test_removes_entry_for_removed_transaction(self, sample_account, transactions, entry_data, existing_entry):
        journal = Journal(
            journal_id="journal-1",
            account=sample_account,
            description="January journal",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
            entries=[existing_entry],
        )
        grouped = {"upsert": [], "remove": [entry_data]}

        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=journal):
            with patch("balanceai.helpers.journal_entry.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai.helpers.journal_entry.finder_find_journal_entry", return_value=existing_entry):
                    with patch("balanceai.helpers.journal_entry.storage_update_journal"):
                        result = handle_create_or_update_journal_entries_for_transactions("journal-1", transactions)

        assert result["entries"] == []

    def test_skips_remove_when_entry_not_found(self, sample_account, transactions, entry_data, existing_entry):
        # Journal has an unrelated entry. The remove target is not found by the finder,
        # so the unrelated entry must remain untouched.
        journal = Journal(
            journal_id="journal-1",
            account=sample_account,
            description="January journal",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
            entries=[existing_entry],
        )
        grouped = {"upsert": [], "remove": [entry_data]}

        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=journal):
            with patch("balanceai.helpers.journal_entry.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai.helpers.journal_entry.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry.storage_update_journal"):
                        result = handle_create_or_update_journal_entries_for_transactions("journal-1", transactions)

        assert len(result["entries"]) == 1
        assert result["entries"][0]["journal_entry_id"] == existing_entry.journal_entry_id

    def test_empty_transactions_leaves_journal_unchanged(self, empty_journal):
        grouped = {"upsert": [], "remove": []}

        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai.helpers.journal_entry.storage_update_journal"):
                    result = handle_create_or_update_journal_entries_for_transactions("journal-1", {})

        assert result["entries"] == []

    def test_upserts_multiple_entries(self, empty_journal, transactions):
        two_entries = [
            JournalEntryData(
                date=datetime.date(2026, 1, 27),
                account=JournalAccount.EXPENSE,
                description="Grocery purchase",
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
        ]
        grouped = {"upsert": two_entries, "remove": []}

        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai.helpers.journal_entry.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry.storage_update_journal"):
                        result = handle_create_or_update_journal_entries_for_transactions("journal-1", transactions)

        assert len(result["entries"]) == 2

    def test_storage_update_called_once(self, empty_journal, transactions, entry_data):
        grouped = {"upsert": [entry_data], "remove": []}

        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai.helpers.journal_entry.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry.storage_update_journal") as mock_save:
                        handle_create_or_update_journal_entries_for_transactions("journal-1", transactions)

        mock_save.assert_called_once_with(empty_journal)

    def test_returns_journal_as_dict(self, empty_journal, transactions, entry_data):
        grouped = {"upsert": [entry_data], "remove": []}

        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai.helpers.journal_entry.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry.storage_update_journal"):
                        result = handle_create_or_update_journal_entries_for_transactions("journal-1", transactions)

        assert isinstance(result, dict)
        assert "journal_id" in result
        assert "entries" in result

    def test_passes_transactions_to_extractor(self, empty_journal):
        grouped = {"upsert": [], "remove": []}
        txns = {"added": [{"transaction_id": "txn-42"}], "modified": [], "removed": []}

        with patch("balanceai.helpers.journal_entry.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry.extract_journal_entries_from_transactions", return_value=grouped) as mock_extract:
                with patch("balanceai.helpers.journal_entry.storage_update_journal"):
                    handle_create_or_update_journal_entries_for_transactions("journal-1", txns)

        mock_extract.assert_called_once_with(txns)
