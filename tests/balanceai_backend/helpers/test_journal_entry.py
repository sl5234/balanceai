import datetime
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

sys.modules.setdefault("anthropic", MagicMock())

from balanceai_backend.helpers.journal_entry_helper import (
    handle_sync_journal_entries_from_receipt,
    handle_sync_journal_entries_from_transactions,
    handle_sync_journal_entries_from_bank_statement,
)
from balanceai_backend.models.account import Account, AccountType
from balanceai_backend.models.bank import Bank
from balanceai_backend.models.journal import (
    Journal,
    JournalAccount,
    JournalEntry,
    GeneratedJournalEntry,
    GeneratedJournalEntrySet,
)
from balanceai_backend.db import conn
from balanceai_backend.models.transaction import Transaction


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
    return GeneratedJournalEntry(
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
    return GeneratedJournalEntrySet(entries=[
        entry_data,
        GeneratedJournalEntry(
            date=datetime.date(2026, 1, 27),
            account=JournalAccount.CASH,
            description="Grocery purchase at Trader Joe's",
            debit=Decimal("0.00"),
            credit=Decimal("32.02"),
        ),
    ])


class TestHandleCreateOrUpdateJournalEntriesForReceipt:
    def test_raises_when_journal_not_found(self, receipt_path):
        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[]):
            with pytest.raises(ValueError, match="journal-999"):
                handle_sync_journal_entries_from_receipt("journal-999", receipt_path)

    def test_creates_new_entry_when_no_match(self, empty_journal, receipt_path, ocr_result):
        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                        result = handle_sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert len(result["entries"]) == 2
        descriptions = {e["description"] for e in result["entries"]}
        assert "Grocery purchase at Trader Joe's" in descriptions

    def test_new_entry_gets_fresh_id(self, empty_journal, receipt_path, ocr_result):
        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
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

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[journal]):
            with patch("balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", side_effect=[existing_entry, None]):
                    with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                        result = handle_sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert len(result["entries"]) == 2
        expense = next(e for e in result["entries"] if e["account"] == JournalAccount.NON_ESSENTIALS_EXPENSE.value)
        assert expense["journal_entry_id"] == "original-id"
        assert expense["description"] == "Grocery purchase at Trader Joe's"
        assert expense["debit"] == "32.02"

    def test_adds_multiple_entries(self, empty_journal, receipt_path):
        double_entry_result = GeneratedJournalEntrySet(entries=[
            GeneratedJournalEntry(
                date=datetime.date(2026, 1, 27),
                account=JournalAccount.NON_ESSENTIALS_EXPENSE,
                description="Grocery purchase at Trader Joe's",
                debit=Decimal("32.02"),
                credit=Decimal("0.00"),
            ),
            GeneratedJournalEntry(
                date=datetime.date(2026, 1, 27),
                account=JournalAccount.CASH,
                description="Payment via Visa",
                debit=Decimal("0.00"),
                credit=Decimal("32.02"),
            ),
        ])

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=double_entry_result):
                with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                        result = handle_sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert len(result["entries"]) == 2

    def test_no_entries_from_ocr_leaves_journal_unchanged(self, empty_journal, receipt_path):
        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=GeneratedJournalEntrySet(entries=[])):
                with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                    result = handle_sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert result["entries"] == []

    def test_storage_update_called_once(self, empty_journal, receipt_path, ocr_result):
        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal") as mock_save:
                        handle_sync_journal_entries_from_receipt("journal-1", receipt_path)

        mock_save.assert_called_once_with(empty_journal, conn)

    def test_returns_journal_as_dict(self, empty_journal, receipt_path, ocr_result):
        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result):
                with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                        result = handle_sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert isinstance(result, dict)
        assert "journal_id" in result
        assert "entries" in result

    def test_passes_file_bytes_and_mime_type_to_ocr(self, empty_journal, receipt_path, ocr_result):
        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic", return_value=ocr_result) as mock_ocr:
                with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                        handle_sync_journal_entries_from_receipt("journal-1", receipt_path)

        mock_ocr.assert_called_once()
        call_kwargs = mock_ocr.call_args.kwargs
        assert call_kwargs["content"] == b"fake-image-data"
        assert call_kwargs["mime_type"] == "image/jpeg"
        assert call_kwargs["output_format"] == GeneratedJournalEntrySet


# ---------------------------------------------------------------------------
# handle_sync_journal_entries_from_transactions
# ---------------------------------------------------------------------------


@pytest.fixture
def transactions():
    return {"added": [{"transaction_id": "txn-1"}], "modified": [], "removed": []}


class TestHandleCreateOrUpdateJournalEntriesForTransactions:
    def test_raises_when_journal_not_found(self, transactions):
        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[]):
            with pytest.raises(ValueError, match="journal-999"):
                handle_sync_journal_entries_from_transactions("journal-999", transactions)

    def test_creates_new_entry_for_added_transaction(self, empty_journal, transactions, entry_data):
        grouped = {"upsert": [entry_data], "remove": []}

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
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

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=existing_entry):
                    with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
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

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=existing_entry):
                    with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
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

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                        result = handle_sync_journal_entries_from_transactions("journal-1", transactions)

        assert len(result["entries"]) == 1
        assert result["entries"][0]["journal_entry_id"] == existing_entry.journal_entry_id

    def test_empty_transactions_leaves_journal_unchanged(self, empty_journal):
        grouped = {"upsert": [], "remove": []}

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                    result = handle_sync_journal_entries_from_transactions("journal-1", {})

        assert result["entries"] == []

    def test_upserts_multiple_entries(self, empty_journal, transactions):
        two_entries = [
            GeneratedJournalEntry(
                date=datetime.date(2026, 1, 27),
                account=JournalAccount.NON_ESSENTIALS_EXPENSE,
                description="Grocery purchase",
                debit=Decimal("32.02"),
                credit=Decimal("0.00"),
            ),
            GeneratedJournalEntry(
                date=datetime.date(2026, 1, 27),
                account=JournalAccount.CASH,
                description="Payment via Visa",
                debit=Decimal("0.00"),
                credit=Decimal("32.02"),
            ),
        ]
        grouped = {"upsert": two_entries, "remove": []}

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                        result = handle_sync_journal_entries_from_transactions("journal-1", transactions)

        assert len(result["entries"]) == 2

    def test_storage_update_called_once(self, empty_journal, transactions, entry_data):
        grouped = {"upsert": [entry_data], "remove": []}

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal") as mock_save:
                        handle_sync_journal_entries_from_transactions("journal-1", transactions)

        mock_save.assert_called_once_with(empty_journal, conn)

    def test_returns_journal_as_dict(self, empty_journal, transactions, entry_data):
        grouped = {"upsert": [entry_data], "remove": []}

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped):
                with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                    with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                        result = handle_sync_journal_entries_from_transactions("journal-1", transactions)

        assert isinstance(result, dict)
        assert "journal_id" in result
        assert "entries" in result

    def test_passes_transactions_to_extractor(self, empty_journal):
        grouped = {"upsert": [], "remove": []}
        txns = {"added": [{"transaction_id": "txn-42"}], "modified": [], "removed": []}

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_transactions", return_value=grouped) as mock_extract:
                with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
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
    return GeneratedJournalEntry(
        date=datetime.date(2026, 1, 25),
        account=JournalAccount.NON_ESSENTIALS_EXPENSE,
        description="Lyft ride purchase.",
        debit=Decimal("12.00"),
        credit=Decimal("0.00"),
        category="rideshare",
    )


@pytest.fixture
def cash_entry_data():
    return GeneratedJournalEntry(
        date=datetime.date(2026, 1, 25),
        account=JournalAccount.CASH,
        description="Lyft ride purchase.",
        debit=Decimal("0.00"),
        credit=Decimal("12.00"),
        category="rideshare",
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
        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[]):
            with pytest.raises(ValueError, match="journal-999"):
                handle_sync_journal_entries_from_bank_statement("journal-999", "/path/to/statement.pdf")

    def test_creates_new_entries_for_single_transaction(self, empty_journal, sample_transaction, expense_entry_data, cash_entry_data):
        mock_parser = self._make_parser([sample_transaction])

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", return_value=[expense_entry_data, cash_entry_data]):
                    with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                        with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
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

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", return_value=[expense_entry_data]):
                    with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=bank_statement_existing_entry):
                        with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                            result = handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        assert len(result["entries"]) == 1
        assert result["entries"][0]["journal_entry_id"] == "original-id"
        assert result["entries"][0]["description"] == "Lyft ride purchase."
        assert result["entries"][0]["debit"] == "12.00"

    def test_no_transactions_leaves_journal_unchanged(self, empty_journal):
        mock_parser = self._make_parser([])

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                    result = handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        assert result["entries"] == []

    def test_multiple_entries_per_transaction(self, empty_journal, sample_transaction, expense_entry_data, cash_entry_data):
        mock_parser = self._make_parser([sample_transaction])

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", return_value=[expense_entry_data, cash_entry_data]):
                    with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                        with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
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
        gas_expense = GeneratedJournalEntry(
            date=datetime.date(2026, 1, 26),
            account=JournalAccount.ESSENTIALS_EXPENSE,
            description="Gas purchase at Shell.",
            debit=Decimal("21.77"),
            credit=Decimal("0.00"),
            category="gas",
        )
        gas_cash = GeneratedJournalEntry(
            date=datetime.date(2026, 1, 26),
            account=JournalAccount.CASH,
            description="Gas purchase at Shell.",
            debit=Decimal("0.00"),
            credit=Decimal("21.77"),
            category="gas",
        )
        mock_parser = self._make_parser([txn1, txn2])

        def extract_side_effect(txn):
            return [expense_entry_data, cash_entry_data] if txn.id == "txn-1" else [gas_expense, gas_cash]

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", side_effect=extract_side_effect):
                    with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                        with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                            result = handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        assert len(result["entries"]) == 4

    def test_parser_error_propagates_without_saving(self, empty_journal):
        mock_parser = MagicMock()
        mock_parser.parse.side_effect = ValueError("Balance mismatch")

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal") as mock_save:
                    with pytest.raises(ValueError, match="Balance mismatch"):
                        handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        mock_save.assert_not_called()

    def test_uses_bank_from_journal_account(self, empty_journal):
        mock_parser = self._make_parser([])

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser) as mock_get_parser:
                with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                    handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        mock_get_parser.assert_called_once_with(Bank.CHASE)

    def test_parser_called_with_file_path(self, empty_journal):
        mock_parser = self._make_parser([])
        file_path = "/path/to/statement.pdf"

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
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

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", return_value=[expense_entry_data]) as mock_extract:
                    with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                        with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                            handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        assert mock_extract.call_count == 2
        mock_extract.assert_any_call(txn1)
        mock_extract.assert_any_call(txn2)

    def test_storage_update_called_once(self, empty_journal, sample_transaction, expense_entry_data):
        mock_parser = self._make_parser([sample_transaction])

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", return_value=[expense_entry_data]):
                    with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                        with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal") as mock_save:
                            handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        mock_save.assert_called_once_with(empty_journal, conn)

    def test_returns_journal_as_dict(self, empty_journal):
        mock_parser = self._make_parser([])

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                    result = handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        assert isinstance(result, dict)
        assert "journal_id" in result
        assert "entries" in result

    # ---------------------------------------------------------------------------
    # Re-categorization step
    # ---------------------------------------------------------------------------

    def test_recategorizes_null_category_entries(self, empty_journal, sample_transaction):
        null_entry = GeneratedJournalEntry(
            date=datetime.date(2026, 1, 25),
            account=JournalAccount.NON_ESSENTIALS_EXPENSE,
            description="Uncategorized transaction from Rudy's.",
            debit=Decimal("25.00"),
            credit=Decimal("0.00"),
            category=None,
        )
        mock_parser = self._make_parser([sample_transaction])

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", return_value=[null_entry]):
                    with patch("balanceai_backend.helpers.journal_entry_helper.generate_transaction_category", return_value=null_entry) as mock_recategorize:
                        with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                            with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                                handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        mock_recategorize.assert_called_once_with(null_entry)

    def test_skips_recategorization_when_all_entries_categorized(self, empty_journal, sample_transaction, expense_entry_data, cash_entry_data):
        mock_parser = self._make_parser([sample_transaction])

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", return_value=[expense_entry_data, cash_entry_data]):
                    with patch("balanceai_backend.helpers.journal_entry_helper.generate_transaction_category") as mock_recategorize:
                        with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                            with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                                handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        mock_recategorize.assert_not_called()

    def test_recategorized_entry_is_used_in_journal(self, empty_journal, sample_transaction):
        null_entry = GeneratedJournalEntry(
            date=datetime.date(2026, 1, 25),
            account=JournalAccount.NON_ESSENTIALS_EXPENSE,
            description="Uncategorized transaction from Rudy's.",
            debit=Decimal("25.00"),
            credit=Decimal("0.00"),
            category=None,
        )
        recategorized = null_entry.model_copy(update={
            "description": "Haircut at Rudy's.",
            "category": "haircut",
        })
        mock_parser = self._make_parser([sample_transaction])

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", return_value=[null_entry]):
                    with patch("balanceai_backend.helpers.journal_entry_helper.generate_transaction_category", return_value=recategorized):
                        with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                            with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                                result = handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        assert result["entries"][0]["description"] == "Haircut at Rudy's."
        assert result["entries"][0]["category"] == "haircut"

    def test_only_null_category_entries_are_recategorized(self, empty_journal, sample_transaction, expense_entry_data):
        null_entry = GeneratedJournalEntry(
            date=datetime.date(2026, 1, 25),
            account=JournalAccount.CASH,
            description="Uncategorized transaction from Rudy's.",
            debit=Decimal("0.00"),
            credit=Decimal("25.00"),
            category=None,
        )
        mock_parser = self._make_parser([sample_transaction])

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", return_value=[expense_entry_data, null_entry]):
                    with patch("balanceai_backend.helpers.journal_entry_helper.generate_transaction_category", return_value=null_entry) as mock_recategorize:
                        with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                            with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                                handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        mock_recategorize.assert_called_once_with(null_entry)

    def test_all_null_category_entries_are_recategorized(self, empty_journal, sample_transaction):
        null_entry_1 = GeneratedJournalEntry(
            date=datetime.date(2026, 1, 25),
            account=JournalAccount.NON_ESSENTIALS_EXPENSE,
            description="Uncategorized transaction from Rudy's.",
            debit=Decimal("25.00"),
            credit=Decimal("0.00"),
            category=None,
        )
        null_entry_2 = GeneratedJournalEntry(
            date=datetime.date(2026, 1, 25),
            account=JournalAccount.CASH,
            description="Uncategorized transaction from Rudy's.",
            debit=Decimal("0.00"),
            credit=Decimal("25.00"),
            category=None,
        )
        mock_parser = self._make_parser([sample_transaction])

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", return_value=[null_entry_1, null_entry_2]):
                    with patch("balanceai_backend.helpers.journal_entry_helper.generate_transaction_category", side_effect=lambda e: e) as mock_recategorize:
                        with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                            with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                                handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        assert mock_recategorize.call_count == 2

    def test_rate_limit_in_step2_does_not_rerun_step1(self, empty_journal, sample_transaction):
        null_entry = GeneratedJournalEntry(
            date=datetime.date(2026, 1, 25),
            account=JournalAccount.NON_ESSENTIALS_EXPENSE,
            description="Uncategorized transaction from Rudy's.",
            debit=Decimal("25.00"),
            credit=Decimal("0.00"),
            category=None,
        )
        recategorized = null_entry.model_copy(update={"category": "dining"})
        mock_parser = self._make_parser([sample_transaction])

        FakeRateLimitError = type("RateLimitError", (Exception,), {})

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", return_value=[null_entry]) as mock_extract:
                    with patch("balanceai_backend.helpers.journal_entry_helper.generate_transaction_category", side_effect=[FakeRateLimitError(), recategorized]) as mock_recategorize:
                        with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                            with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                                with patch("balanceai_backend.helpers.journal_entry_helper.anthropic") as mock_anthropic:
                                    mock_anthropic.RateLimitError = FakeRateLimitError
                                    with patch("balanceai_backend.helpers.journal_entry_helper.time.sleep"):
                                        handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        assert mock_extract.call_count == 1
        assert mock_recategorize.call_count == 2

    def test_null_category_entry_still_added_when_recategorization_returns_unchanged(self, empty_journal, sample_transaction):
        null_entry = GeneratedJournalEntry(
            date=datetime.date(2026, 1, 25),
            account=JournalAccount.NON_ESSENTIALS_EXPENSE,
            description="Uncategorized transaction from Rudy's.",
            debit=Decimal("25.00"),
            credit=Decimal("0.00"),
            category=None,
        )
        mock_parser = self._make_parser([sample_transaction])

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", return_value=[null_entry]):
                    with patch("balanceai_backend.helpers.journal_entry_helper.generate_transaction_category", return_value=null_entry):
                        with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                            with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                                result = handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

        assert len(result["entries"]) == 1

    # ---------------------------------------------------------------------------
    # Response redaction
    # ---------------------------------------------------------------------------

    def _make_entry_data(self, i):
        return GeneratedJournalEntry(
            date=datetime.date(2026, 1, i + 1),
            account=JournalAccount.NON_ESSENTIALS_EXPENSE,
            description=f"Transaction {i}",
            debit=Decimal("10.00"),
            credit=Decimal("0.00"),
            category="misc",
        )

    def _sync_with_n_entries(self, empty_journal, n):
        entries = [self._make_entry_data(i) for i in range(n)]
        transactions = [MagicMock() for _ in range(n)]
        mock_parser = self._make_parser(transactions)

        with patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[empty_journal]):
            with patch("balanceai_backend.helpers.journal_entry_helper.get_parser", return_value=mock_parser):
                with patch("balanceai_backend.helpers.journal_entry_helper.extract_journal_entries_from_bank_statement_transaction", side_effect=lambda txn: [entries[transactions.index(txn)]]):
                    with patch("balanceai_backend.helpers.journal_entry_helper.finder_find_journal_entry", return_value=None):
                        with patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"):
                            return handle_sync_journal_entries_from_bank_statement("journal-1", "/path/to/statement.pdf")

    def test_redaction_returns_all_entries_when_empty(self, empty_journal):
        result = self._sync_with_n_entries(empty_journal, 0)
        assert result["entries"] == []
        assert "entries_redacted" not in result

    def test_redaction_returns_all_entries_when_below_threshold(self, empty_journal):
        result = self._sync_with_n_entries(empty_journal, 4)
        assert len(result["entries"]) == 4
        assert "entries_redacted" not in result

    def test_redaction_returns_all_entries_when_exactly_5(self, empty_journal):
        result = self._sync_with_n_entries(empty_journal, 5)
        assert len(result["entries"]) == 5
        assert "entries_redacted" not in result

    def test_redaction_returns_first_5_entries_when_above_threshold(self, empty_journal):
        result = self._sync_with_n_entries(empty_journal, 6)
        assert len(result["entries"]) == 5

    def test_redaction_entries_redacted_count_is_correct(self, empty_journal):
        result = self._sync_with_n_entries(empty_journal, 8)
        assert result["entries_redacted"] == 3

    def test_redaction_entries_are_in_original_order(self, empty_journal):
        result = self._sync_with_n_entries(empty_journal, 7)
        descriptions = [e["description"] for e in result["entries"]]
        assert descriptions == [f"Transaction {i}" for i in range(5)]
