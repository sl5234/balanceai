import datetime
import json
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

sys.modules.setdefault("anthropic", MagicMock())
sys.modules.setdefault("tavily", MagicMock())

from balanceai.models.journal import GeneratedJournalEntry, GeneratedJournalEntrySet, JournalAccount
from balanceai.models.transaction import Transaction
from balanceai.utils.journal_entry_util import (
    extract_merchant,
    extract_journal_entries_from_bank_statement_transaction,
    generate_transaction_category,
)


# ---------------------------------------------------------------------------
# extract_merchant
# ---------------------------------------------------------------------------


class TestExtractMerchant:
    def test_strips_leading_date(self):
        assert extract_merchant("01/28 Uber *One Membership San Francisco CA") == "Uber *One Membership San Francisco CA"

    def test_strips_card_purchase_prefix_and_date(self):
        assert extract_merchant("Card Purchase 01/25 Shell Oil Seattle WA") == "Shell Oil Seattle WA"

    def test_strips_card_purchase_with_pin_prefix_and_date(self):
        assert extract_merchant("Card Purchase With Pin 01/25 Shell Oil Seattle WA") == "Shell Oil Seattle WA"

    def test_strips_recurring_card_purchase_prefix(self):
        assert extract_merchant("Recurring Card Purchase 01/27 Adobe Systems Inc.") == "Adobe Systems Inc."

    def test_strips_leading_date_and_prefix_together(self):
        result = extract_merchant("01/28 Card Purchase With Pin 01/28 Uber *One Membership San Francisco CA -9.99 6,271.43")
        assert result == "Uber *One Membership San Francisco CA"

    def test_strips_trailing_amounts(self):
        assert extract_merchant("Uber *One Membership San Francisco CA -9.99 6,271.43") == "Uber *One Membership San Francisco CA"

    def test_leaves_plain_description_unchanged(self):
        assert extract_merchant("Zelle Payment To John Smith") == "Zelle Payment To John Smith"

    def test_case_insensitive_prefix_matching(self):
        assert extract_merchant("card purchase 01/25 Shell Oil Seattle WA") == "Shell Oil Seattle WA"

    def test_strips_duplicate_leading_date_and_trailing_amounts_from_payment(self):
        assert extract_merchant("02/04 02/04 Payment To Chase Card Ending IN 1497 -60.78 6,761.52") == "02/04 Payment To Chase Card Ending IN 1497"

    def test_strips_card_purchase_with_phone_number_and_card_suffix(self):
        assert extract_merchant("01/26 Card Purchase 01/25 Shell Oil 57445959901 Seattle WA Card 0442 -21.77 8,184.10") == "Shell Oil 57445959901 Seattle WA Card 0442"

    def test_strips_card_purchase_with_pin_pending_merchant(self):
        assert extract_merchant("01/28 Card Purchase With Pin 01/27 Uber * Eats Pending San Francisco CA Card -74.04 6,281.42") == "Uber * Eats Pending San Francisco CA Card"


# ---------------------------------------------------------------------------
# generate_transaction_category
# ---------------------------------------------------------------------------


@pytest.fixture
def uncategorized_entry():
    return GeneratedJournalEntry(
        date=datetime.date(2026, 1, 25),
        account=JournalAccount.NON_ESSENTIALS_EXPENSE,
        description="Uncategorized transaction from Rudy's.",
        debit=Decimal("25.00"),
        credit=Decimal("0.00"),
        recipient="Rudy's",
        category=None,
    )


class TestGenerateTransactionCategory:
    def test_returns_entry_with_category_from_cache(self, uncategorized_entry):
        cache = {"rudy's": "haircut"}
        with patch("balanceai.utils.journal_entry_util.load_merchant_context_cache", return_value=cache):
            with patch("balanceai.utils.journal_entry_util.tavily_service.search") as mock_tavily:
                with patch("balanceai.utils.journal_entry_util.anthropic_service.messages") as mock_llm:
                    result = generate_transaction_category(uncategorized_entry)

        assert result.category == "haircut"
        mock_tavily.assert_not_called()
        mock_llm.assert_not_called()

    def test_calls_tavily_when_recipient_not_in_cache(self, uncategorized_entry):
        with patch("balanceai.utils.journal_entry_util.load_merchant_context_cache", return_value={}):
            with patch("balanceai.utils.journal_entry_util.tavily_service.search", return_value=None) as mock_tavily:
                with patch("balanceai.utils.journal_entry_util.anthropic_service.messages"):
                    generate_transaction_category(uncategorized_entry)

        mock_tavily.assert_called_once()

    def test_returns_entry_unchanged_and_logs_warning_when_tavily_returns_nothing(self, uncategorized_entry, caplog):
        import logging
        with patch("balanceai.utils.journal_entry_util.load_merchant_context_cache", return_value={}):
            with patch("balanceai.utils.journal_entry_util.tavily_service.search", return_value=None):
                with caplog.at_level(logging.WARNING, logger="balanceai.utils.journal_entry_util"):
                    result = generate_transaction_category(uncategorized_entry)

        assert result is uncategorized_entry
        assert "Rudy's" in caplog.text

    def test_calls_llm_with_tavily_context(self, uncategorized_entry):
        categorized = uncategorized_entry.model_copy(update={"category": "haircut"})
        with patch("balanceai.utils.journal_entry_util.load_merchant_context_cache", return_value={}):
            with patch("balanceai.utils.journal_entry_util.tavily_service.search", return_value="Rudy's is a barbershop."):
                with patch("balanceai.utils.journal_entry_util.anthropic_service.messages", return_value="{}") as mock_llm:
                    with patch("balanceai.utils.journal_entry_util._extract_json", return_value=categorized.model_dump_json()):
                        with patch("balanceai.utils.journal_entry_util.save_merchant_context_cache"):
                            generate_transaction_category(uncategorized_entry)

        call_kwargs = mock_llm.call_args.kwargs
        assert "Rudy's is a barbershop." in call_kwargs["system_instruction"]

    def test_returns_llm_result_with_category(self, uncategorized_entry):
        categorized = uncategorized_entry.model_copy(update={"category": "haircut", "description": "Haircut at Rudy's."})
        with patch("balanceai.utils.journal_entry_util.load_merchant_context_cache", return_value={}):
            with patch("balanceai.utils.journal_entry_util.tavily_service.search", return_value="Rudy's is a barbershop."):
                with patch("balanceai.utils.journal_entry_util.anthropic_service.messages", return_value="{}"):
                    with patch("balanceai.utils.journal_entry_util._extract_json", return_value=categorized.model_dump_json()):
                        with patch("balanceai.utils.journal_entry_util.save_merchant_context_cache"):
                            result = generate_transaction_category(uncategorized_entry)

        assert result.category == "haircut"
        assert result.description == "Haircut at Rudy's."

    def test_writes_recipient_to_category_cache_when_llm_assigns_category(self, uncategorized_entry):
        categorized = uncategorized_entry.model_copy(update={"category": "haircut"})
        with patch("balanceai.utils.journal_entry_util.load_merchant_context_cache", return_value={}):
            with patch("balanceai.utils.journal_entry_util.tavily_service.search", return_value="Rudy's is a barbershop."):
                with patch("balanceai.utils.journal_entry_util.anthropic_service.messages", return_value="{}"):
                    with patch("balanceai.utils.journal_entry_util._extract_json", return_value=categorized.model_dump_json()):
                        with patch("balanceai.utils.journal_entry_util.save_merchant_context_cache") as mock_save:
                            generate_transaction_category(uncategorized_entry)

        saved_cache = mock_save.call_args.args[0]
        assert saved_cache["rudy's"] == "haircut"

    def test_does_not_write_cache_when_llm_returns_null_category(self, uncategorized_entry):
        with patch("balanceai.utils.journal_entry_util.load_merchant_context_cache", return_value={}):
            with patch("balanceai.utils.journal_entry_util.tavily_service.search", return_value="Rudy's is a barbershop."):
                with patch("balanceai.utils.journal_entry_util.anthropic_service.messages", return_value="{}"):
                    with patch("balanceai.utils.journal_entry_util._extract_json", return_value=uncategorized_entry.model_dump_json()):
                        with patch("balanceai.utils.journal_entry_util.save_merchant_context_cache") as mock_save:
                            generate_transaction_category(uncategorized_entry)

        mock_save.assert_not_called()

    def test_returns_entry_unchanged_when_llm_also_returns_null_category(self, uncategorized_entry):
        with patch("balanceai.utils.journal_entry_util.load_merchant_context_cache", return_value={}):
            with patch("balanceai.utils.journal_entry_util.tavily_service.search", return_value="Rudy's is a barbershop."):
                with patch("balanceai.utils.journal_entry_util.anthropic_service.messages", return_value="{}"):
                    with patch("balanceai.utils.journal_entry_util._extract_json", return_value=uncategorized_entry.model_dump_json()):
                        with patch("balanceai.utils.journal_entry_util.save_merchant_context_cache"):
                            result = generate_transaction_category(uncategorized_entry)

        assert result.category is None


# ---------------------------------------------------------------------------
# extract_journal_entries_from_bank_statement_transaction
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_transaction():
    return Transaction(
        id="txn-1",
        account_id="acct-1",
        posting_date=datetime.date(2026, 1, 25),
        description="Card Purchase 01/25 Shell Oil Seattle WA",
        amount=Decimal("-21.77"),
        previous_balance=Decimal("1000.00"),
        new_balance=Decimal("978.23"),
    )


@pytest.fixture
def sample_entry():
    return GeneratedJournalEntry(
        date=datetime.date(2026, 1, 25),
        account=JournalAccount.ESSENTIALS_EXPENSE,
        description="Gas purchase at Shell.",
        debit=Decimal("21.77"),
        credit=Decimal("0.00"),
        category="gas",
    )


class TestExtractJournalEntriesFromBankStatementTransaction:
    def test_calls_llm_with_transaction_json(self, sample_transaction, sample_entry):
        llm_response = GeneratedJournalEntrySet(entries=[sample_entry]).model_dump_json()
        with patch("balanceai.utils.journal_entry_util.load_merchant_context_cache", return_value={}):
            with patch("balanceai.utils.journal_entry_util.anthropic_service.messages", return_value="{}") as mock_llm:
                with patch("balanceai.utils.journal_entry_util._extract_json", return_value=llm_response):
                    extract_journal_entries_from_bank_statement_transaction(sample_transaction)

        call_kwargs = mock_llm.call_args.kwargs
        assert json.loads(call_kwargs["content"]) == sample_transaction.to_dict()

    def test_passes_merchant_cache_as_context(self, sample_transaction, sample_entry):
        cache = {"shell oil seattle wa": "gas"}
        llm_response = GeneratedJournalEntrySet(entries=[sample_entry]).model_dump_json()
        with patch("balanceai.utils.journal_entry_util.load_merchant_context_cache", return_value=cache):
            with patch("balanceai.utils.journal_entry_util.anthropic_service.messages", return_value="{}") as mock_llm:
                with patch("balanceai.utils.journal_entry_util._extract_json", return_value=llm_response):
                    extract_journal_entries_from_bank_statement_transaction(sample_transaction)

        call_kwargs = mock_llm.call_args.kwargs
        assert str(cache) in call_kwargs["system_instruction"]

    def test_returns_entries_from_llm_response(self, sample_transaction, sample_entry):
        llm_response = GeneratedJournalEntrySet(entries=[sample_entry]).model_dump_json()
        with patch("balanceai.utils.journal_entry_util.load_merchant_context_cache", return_value={}):
            with patch("balanceai.utils.journal_entry_util.anthropic_service.messages", return_value="{}"):
                with patch("balanceai.utils.journal_entry_util._extract_json", return_value=llm_response):
                    result = extract_journal_entries_from_bank_statement_transaction(sample_transaction)

        assert len(result) == 1
        assert result[0].description == "Gas purchase at Shell."
        assert result[0].category == "gas"

