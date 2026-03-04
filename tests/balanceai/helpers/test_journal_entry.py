import datetime
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

sys.modules.setdefault("anthropic", MagicMock())

from balanceai.helpers.journal_entry_helper import (
    handle_sync_journal_entries_from_receipt,
    handle_sync_journal_entries_from_transactions,
    handle_sync_journal_entries_from_bank_statement,
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
from balanceai.models.transaction import Transaction


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
        account=JournalAccount.NON_ESSENTIALS_EXPENSE,
        description="Grocery purchase at Trader Joe's",
        debit=Decimal("32.02"),
        credit=Decimal("0.00"),
    )


@pytest.fixture
def existing_entry():
    return JournalEntry(
        journal_entry_id="original-id",
        date=datetime.date(2026, 1, 27),
        account=JournalAccount.NON_ESSENTIALS_EXPENSE,
        description="Old description",
        debit=Decimal("30.00"),
        credit=Decimal("0.00"),
    )


# ---------------------------------------------------------------------------
# handle_sync_journal_entries_from_receipt
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
        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=None):
            with pytest.raises(ValueError, match="journal-999"):
                handle_sync_journal_entries_from_receipt("journal-999", receipt_path)

    def test_creates_new_entry_when_no_match(self, empty_journal, receipt_path, ocr_result):
        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                        result = handle_sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert len(result["entries"]) == 1
        assert result["entries"][0]["description"] == "Grocery purchase at Trader Joe's"

    def test_new_entry_gets_fresh_id(self, empty_journal, receipt_path, ocr_result):
        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                        result = handle_sync_journal_entries_from_receipt("journal-1", receipt_path)

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

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=existing_entry):
                    with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                        result = handle_sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert len(result["entries"]) == 1
        assert result["entries"][0]["journal_entry_id"] == "original-id"
        assert result["entries"][0]["description"] == "Grocery purchase at Trader Joe's"
        assert result["entries"][0]["debit"] == "32.02"

    def test_adds_multiple_entries(self, empty_journal, receipt_path):
        double_entry_result = JournalEntryDataSet(entries=[
            JournalEntryData(
                date=datetime.date(2026, 1, 27),
                account=JournalAccount.NON_ESSENTIALS_EXPENSE,
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

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=double_entry_result):
                with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                        result = handle_sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert len(result["entries"]) == 2

    def test_no_entries_from_ocr_leaves_journal_unchanged(self, empty_journal, receipt_path):
        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=JournalEntryDataSet(entries=[])):
                with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                    result = handle_sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert result["entries"] == []

    def test_storage_update_called_once(self, empty_journal, receipt_path, ocr_result):
        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry_helper.storage_update_journal") as mock_save:
                        handle_sync_journal_entries_from_receipt("journal-1", receipt_path)

        mock_save.assert_called_once_with(empty_journal)

    def test_returns_journal_as_dict(self, empty_journal, receipt_path, ocr_result):
        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                        result = handle_sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert isinstance(result, dict)
        assert "journal_id" in result
        assert "entries" in result

    def test_passes_file_bytes_and_mime_type_to_ocr(self, empty_journal, receipt_path, ocr_result):
        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result) as mock_ocr:
                with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                        handle_sync_journal_entries_from_receipt("journal-1", receipt_path)

        mock_ocr.assert_called_once()
        call_kwargs = mock_ocr.call_args.kwargs
        assert call_kwargs["content"] == b"fake-image-data"
        assert call_kwargs["mime_type"] == "image/jpeg"
        assert call_kwargs["output_format"] == JournalEntryDataSet


# ---------------------------------------------------------------------------
# handle_sync_journal_entries_from_transactions
# ---------------------------------------------------------------------------


@pytest.fixture
def transactions():
    return {"added": [{"transaction_id": "txn-1"}], "modified": [], "removed": []}


class TestHandleCreateOrUpdateJournalEntriesForTransactions:
    def test_raises_when_journal_not_found(self, transactions):
        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=None):
            with pytest.raises(ValueError, match="journal-999"):
                handle_sync_journal_entries_from_transactions("journal-999", transactions)

    def test_creates_new_entry_for_added_transaction(self, empty_journal, transactions, entry_data):
        grouped = {"upsert": [entry_data], "remove": []}

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                        result = handle_sync_journal_entries_from_transactions("journal-1", transactions)

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

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=journal):
            with patch("balanceai.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=existing_entry):
                    with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                        result = handle_sync_journal_entries_from_transactions("journal-1", transactions)

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

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=journal):
            with patch("balanceai.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=existing_entry):
                    with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                        result = handle_sync_journal_entries_from_transactions("journal-1", transactions)

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

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=journal):
            with patch("balanceai.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                        result = handle_sync_journal_entries_from_transactions("journal-1", transactions)

        assert len(result["entries"]) == 1
        assert result["entries"][0]["journal_entry_id"] == existing_entry.journal_entry_id

    def test_empty_transactions_leaves_journal_unchanged(self, empty_journal):
        grouped = {"upsert": [], "remove": []}

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                    result = handle_sync_journal_entries_from_transactions("journal-1", {})

        assert result["entries"] == []

    def test_upserts_multiple_entries(self, empty_journal, transactions):
        two_entries = [
            JournalEntryData(
                date=datetime.date(2026, 1, 27),
                account=JournalAccount.NON_ESSENTIALS_EXPENSE,
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

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                        result = handle_sync_journal_entries_from_transactions("journal-1", transactions)

        assert len(result["entries"]) == 2

    def test_storage_update_called_once(self, empty_journal, transactions, entry_data):
        grouped = {"upsert": [entry_data], "remove": []}

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry_helper.storage_update_journal") as mock_save:
                        handle_sync_journal_entries_from_transactions("journal-1", transactions)

        mock_save.assert_called_once_with(empty_journal)

    def test_returns_journal_as_dict(self, empty_journal, transactions, entry_data):
        grouped = {"upsert": [entry_data], "remove": []}

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                        result = handle_sync_journal_entries_from_transactions("journal-1", transactions)

        assert isinstance(result, dict)
        assert "journal_id" in result
        assert "entries" in result

    def test_passes_transactions_to_extractor(self, empty_journal):
        grouped = {"upsert": [], "remove": []}
        txns = {"added": [{"transaction_id": "txn-42"}], "modified": [], "removed": []}

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped) as mock_extract:
                with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                    handle_sync_journal_entries_from_transactions("journal-1", txns)

        mock_extract.assert_called_once_with(txns)


# ---------------------------------------------------------------------------
# handle_sync_journal_entries_from_bank_statement
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_transaction():
    return Transaction(
        id="txn-id-1",
        account_id="acct-1",
        posting_date=datetime.date(2026, 1, 25),
        description="Lyft Ride",
        amount=Decimal("-12.00"),
        previous_balance=Decimal("1000.00"),
        new_balance=Decimal("988.00"),
    )


@pytest.fixture
def expense_entry_data():
    return JournalEntryData(
        date=datetime.date(2026, 1, 25),
        account=JournalAccount.NON_ESSENTIALS_EXPENSE,
        description="Lyft ride purchase.",
        debit=Decimal("12.00"),
        credit=Decimal("0.00"),
    )


@pytest.fixture
def cash_entry_data():
    return JournalEntryData(
        date=datetime.date(2026, 1, 25),
        account=JournalAccount.CASH,
        description="Lyft ride purchase.",
        debit=Decimal("0.00"),
        credit=Decimal("12.00"),
    )


@pytest.fixture
def bank_statement_existing_entry():
    return JournalEntry(
        journal_entry_id="original-id",
        date=datetime.date(2026, 1, 25),
        account=JournalAccount.NON_ESSENTIALS_EXPENSE,
        description="Old description",
        debit=Decimal("10.00"),
        credit=Decimal("0.00"),
    )


class TestHandleSyncJournalEntriesFromBankStatement:
    def _make_parser(self, transactions):
        mock_parser = MagicMock()
        mock_parser.parse.return_value = (MagicMock(), transactions)
        return mock_parser

    def test_raises_when_journal_not_found(self):
        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=None):
            with pytest.raises(ValueError, match="journal-999"):
                handle_sync_journal_entries_from_bank_statement("journal-999", "/path/to/statement.pdf")

    def test_creates_new_entries_for_single_transaction(self, empty_journal, sample_transaction, expense_entry_data, cash_entry_data):
        mock_parser = self._make_parser([sample_transaction])

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", return_value=[expense_entry_data, cash_entry_data]):
                    with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                        with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                            result = handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        assert len(result["entries"]) == 2

    def test_updates_existing_entry_preserving_id(self, sample_account, sample_transaction, expense_entry_data, bank_statement_existing_entry):
        journal = Journal(
            journal_id="journal-1",
            account=sample_account,
            description="January journal",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
            entries=[bank_statement_existing_entry],
        )
        mock_parser = self._make_parser([sample_transaction])

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=journal):
            with patch("balanceai.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", return_value=[expense_entry_data]):
                    with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=bank_statement_existing_entry):
                        with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                            result = handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        assert len(result["entries"]) == 1
        assert result["entries"][0]["journal_entry_id"] == "original-id"
        assert result["entries"][0]["description"] == "Lyft ride purchase."
        assert result["entries"][0]["debit"] == "12.00"

    def test_no_transactions_leaves_journal_unchanged(self, empty_journal):
        mock_parser = self._make_parser([])

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                    result = handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        assert result["entries"] == []

    def test_multiple_entries_per_transaction(self, empty_journal, sample_transaction, expense_entry_data, cash_entry_data):
        mock_parser = self._make_parser([sample_transaction])

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", return_value=[expense_entry_data, cash_entry_data]):
                    with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                        with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                            result = handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        assert len(result["entries"]) == 2
        accounts = {e["account"] for e in result["entries"]}
        assert accounts == {JournalAccount.NON_ESSENTIALS_EXPENSE.value, JournalAccount.CASH.value}

    def test_multiple_transactions_all_entries_accumulated(self, empty_journal, expense_entry_data, cash_entry_data):
        txn1 = Transaction(
            id="txn-1", account_id="acct-1",
            posting_date=datetime.date(2026, 1, 25), description="Lyft",
            amount=Decimal("-12.00"), previous_balance=Decimal("1000.00"), new_balance=Decimal("988.00"),
        )
        txn2 = Transaction(
            id="txn-2", account_id="acct-1",
            posting_date=datetime.date(2026, 1, 26), description="Shell Gas",
            amount=Decimal("-21.77"), previous_balance=Decimal("988.00"), new_balance=Decimal("966.23"),
        )
        gas_expense = JournalEntryData(
            date=datetime.date(2026, 1, 26),
            account=JournalAccount.ESSENTIALS_EXPENSE,
            description="Gas purchase at Shell.",
            debit=Decimal("21.77"),
            credit=Decimal("0.00"),
        )
        gas_cash = JournalEntryData(
            date=datetime.date(2026, 1, 26),
            account=JournalAccount.CASH,
            description="Gas purchase at Shell.",
            debit=Decimal("0.00"),
            credit=Decimal("21.77"),
        )
        mock_parser = self._make_parser([txn1, txn2])

        def extract_side_effect(txn):
            return [expense_entry_data, cash_entry_data] if txn.id == "txn-1" else [gas_expense, gas_cash]

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", side_effect=extract_side_effect):
                    with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                        with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                            result = handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        assert len(result["entries"]) == 4

    def test_parser_error_propagates_without_saving(self, empty_journal):
        mock_parser = MagicMock()
        mock_parser.parse.side_effect = ValueError("Balance mismatch")

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai.helpers.journal_entry_helper.storage_update_journal") as mock_save:
                    with pytest.raises(ValueError, match="Balance mismatch"):
                        handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        mock_save.assert_not_called()

    def test_uses_bank_from_journal_account(self, empty_journal):
        mock_parser = self._make_parser([])

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry_helper.get_parser", return_value=mock_parser) as mock_get_parser:
                with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                    handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        mock_get_parser.assert_called_once_with(Bank.CHASE)

    def test_parser_called_with_file_path(self, empty_journal):
        mock_parser = self._make_parser([])
        file_path = "/path/to/statement.pdf"

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                    handle_sync_journal_entries_from_bank_statement("journal-1", file_path)

        mock_parser.parse.assert_called_once_with(file_path)

    def test_extract_entries_called_once_per_transaction(self, empty_journal, expense_entry_data):
        txn1 = Transaction(
            id="txn-1", account_id="acct-1",
            posting_date=datetime.date(2026, 1, 25), description="Lyft",
            amount=Decimal("-12.00"), previous_balance=Decimal("1000.00"), new_balance=Decimal("988.00"),
        )
        txn2 = Transaction(
            id="txn-2", account_id="acct-1",
            posting_date=datetime.date(2026, 1, 26), description="Shell",
            amount=Decimal("-21.77"), previous_balance=Decimal("988.00"), new_balance=Decimal("966.23"),
        )
        mock_parser = self._make_parser([txn1, txn2])

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", return_value=[expense_entry_data]) as mock_extract:
                    with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                        with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                            handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        assert mock_extract.call_count == 2
        mock_extract.assert_any_call(txn1)
        mock_extract.assert_any_call(txn2)

    def test_storage_update_called_once(self, empty_journal, sample_transaction, expense_entry_data):
        mock_parser = self._make_parser([sample_transaction])

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", return_value=[expense_entry_data]):
                    with patch("balanceai.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                        with patch("balanceai.helpers.journal_entry_helper.storage_update_journal") as mock_save:
                            handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        mock_save.assert_called_once_with(empty_journal)

    def test_returns_journal_as_dict(self, empty_journal):
        mock_parser = self._make_parser([])

        with patch("balanceai.helpers.journal_entry_helper.find_journal_by_id", return_value=empty_journal):
            with patch("balanceai.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai.helpers.journal_entry_helper.storage_update_journal"):
                    result = handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        assert isinstance(result, dict)
        assert "journal_id" in result
        assert "entries" in result
