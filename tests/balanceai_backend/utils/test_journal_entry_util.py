import datetime
import json
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

sys.modules.setdefault("anthropic", MagicMock())
sys.modules.setdefault("tavily", MagicMock())

from balanceai_backend.models.journal import (
    GeneratedJournalEntry,
    GeneratedJournalEntrySet,
    JournalAccount,
)
from balanceai_backend.models.transaction import Transaction
from balanceai_backend.utils.journal_entry_util import (
    extract_journal_entries_from_bank_statement_transaction,
    generate_transaction_category,
)

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
        with patch(
            "balanceai_backend.utils.journal_entry_util.load_merchant_context_cache",
            return_value=cache,
        ):
            with patch(
                "balanceai_backend.utils.journal_entry_util.tavily_service.search"
            ) as mock_tavily:
                with patch(
                    "balanceai_backend.utils.journal_entry_util.anthropic_service.messages"
                ) as mock_llm:
                    result = generate_transaction_category(uncategorized_entry)

        assert result.category == "haircut"
        mock_tavily.assert_not_called()
        mock_llm.assert_not_called()

    def test_calls_tavily_when_recipient_not_in_cache(self, uncategorized_entry):
        with patch(
            "balanceai_backend.utils.journal_entry_util.load_merchant_context_cache",
            return_value={},
        ):
            with patch(
                "balanceai_backend.utils.journal_entry_util.tavily_service.search",
                return_value=None,
            ) as mock_tavily:
                with patch("balanceai_backend.utils.journal_entry_util.anthropic_service.messages"):
                    generate_transaction_category(uncategorized_entry)

        mock_tavily.assert_called_once()

    def test_returns_entry_unchanged_and_logs_warning_when_tavily_returns_nothing(
        self, uncategorized_entry, caplog
    ):
        import logging

        with patch(
            "balanceai_backend.utils.journal_entry_util.load_merchant_context_cache",
            return_value={},
        ):
            with patch(
                "balanceai_backend.utils.journal_entry_util.tavily_service.search",
                return_value=None,
            ):
                with caplog.at_level(
                    logging.WARNING, logger="balanceai_backend.utils.journal_entry_util"
                ):
                    result = generate_transaction_category(uncategorized_entry)

        assert result is uncategorized_entry
        assert "Rudy's" in caplog.text

    def test_calls_llm_with_tavily_context(self, uncategorized_entry):
        categorized = uncategorized_entry.model_copy(update={"category": "haircut"})
        with patch(
            "balanceai_backend.utils.journal_entry_util.load_merchant_context_cache",
            return_value={},
        ):
            with patch(
                "balanceai_backend.utils.journal_entry_util.tavily_service.search",
                return_value="Rudy's is a barbershop.",
            ):
                with patch(
                    "balanceai_backend.utils.journal_entry_util.anthropic_service.messages",
                    return_value="{}",
                ) as mock_llm:
                    with patch(
                        "balanceai_backend.utils.journal_entry_util._extract_json",
                        return_value=categorized.model_dump_json(),
                    ):
                        with patch(
                            "balanceai_backend.utils.journal_entry_util.save_merchant_context_cache"
                        ):
                            generate_transaction_category(uncategorized_entry)

        call_kwargs = mock_llm.call_args.kwargs
        assert "Rudy's is a barbershop." in call_kwargs["system_instruction"]

    def test_returns_llm_result_with_category(self, uncategorized_entry):
        categorized = uncategorized_entry.model_copy(
            update={"category": "haircut", "description": "Haircut at Rudy's."}
        )
        with patch(
            "balanceai_backend.utils.journal_entry_util.load_merchant_context_cache",
            return_value={},
        ):
            with patch(
                "balanceai_backend.utils.journal_entry_util.tavily_service.search",
                return_value="Rudy's is a barbershop.",
            ):
                with patch(
                    "balanceai_backend.utils.journal_entry_util.anthropic_service.messages",
                    return_value="{}",
                ):
                    with patch(
                        "balanceai_backend.utils.journal_entry_util._extract_json",
                        return_value=categorized.model_dump_json(),
                    ):
                        with patch(
                            "balanceai_backend.utils.journal_entry_util.save_merchant_context_cache"
                        ):
                            result = generate_transaction_category(uncategorized_entry)

        assert result.category == "haircut"
        assert result.description == "Haircut at Rudy's."

    def test_writes_recipient_to_category_cache_when_llm_assigns_category(
        self, uncategorized_entry
    ):
        categorized = uncategorized_entry.model_copy(update={"category": "haircut"})
        with patch(
            "balanceai_backend.utils.journal_entry_util.load_merchant_context_cache",
            return_value={},
        ):
            with patch(
                "balanceai_backend.utils.journal_entry_util.tavily_service.search",
                return_value="Rudy's is a barbershop.",
            ):
                with patch(
                    "balanceai_backend.utils.journal_entry_util.anthropic_service.messages",
                    return_value="{}",
                ):
                    with patch(
                        "balanceai_backend.utils.journal_entry_util._extract_json",
                        return_value=categorized.model_dump_json(),
                    ):
                        with patch(
                            "balanceai_backend.utils.journal_entry_util.save_merchant_context_cache"
                        ) as mock_save:
                            generate_transaction_category(uncategorized_entry)

        saved_cache = mock_save.call_args.args[0]
        assert saved_cache["rudy's"] == "haircut"

    def test_does_not_write_cache_when_llm_returns_null_category(self, uncategorized_entry):
        with patch(
            "balanceai_backend.utils.journal_entry_util.load_merchant_context_cache",
            return_value={},
        ):
            with patch(
                "balanceai_backend.utils.journal_entry_util.tavily_service.search",
                return_value="Rudy's is a barbershop.",
            ):
                with patch(
                    "balanceai_backend.utils.journal_entry_util.anthropic_service.messages",
                    return_value="{}",
                ):
                    with patch(
                        "balanceai_backend.utils.journal_entry_util._extract_json",
                        return_value=uncategorized_entry.model_dump_json(),
                    ):
                        with patch(
                            "balanceai_backend.utils.journal_entry_util.save_merchant_context_cache"
                        ) as mock_save:
                            generate_transaction_category(uncategorized_entry)

        mock_save.assert_not_called()

    def test_returns_entry_unchanged_when_llm_also_returns_null_category(self, uncategorized_entry):
        with patch(
            "balanceai_backend.utils.journal_entry_util.load_merchant_context_cache",
            return_value={},
        ):
            with patch(
                "balanceai_backend.utils.journal_entry_util.tavily_service.search",
                return_value="Rudy's is a barbershop.",
            ):
                with patch(
                    "balanceai_backend.utils.journal_entry_util.anthropic_service.messages",
                    return_value="{}",
                ):
                    with patch(
                        "balanceai_backend.utils.journal_entry_util._extract_json",
                        return_value=uncategorized_entry.model_dump_json(),
                    ):
                        with patch(
                            "balanceai_backend.utils.journal_entry_util.save_merchant_context_cache"
                        ):
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


@pytest.fixture
def sample_entry_set(sample_entry):
    return GeneratedJournalEntrySet(
        entries=[
            sample_entry,
            GeneratedJournalEntry(
                date=datetime.date(2026, 1, 25),
                account=JournalAccount.CASH,
                description="Gas purchase at Shell.",
                debit=Decimal("0.00"),
                credit=Decimal("21.77"),
                category="gas",
            ),
        ]
    )


class TestExtractJournalEntriesFromBankStatementTransaction:
    def test_calls_llm_with_transaction_json(self, sample_transaction, sample_entry_set):
        llm_response = sample_entry_set.model_dump_json()
        with patch(
            "balanceai_backend.utils.journal_entry_util.load_merchant_context_cache",
            return_value={},
        ):
            with patch(
                "balanceai_backend.utils.journal_entry_util.anthropic_service.messages",
                return_value="{}",
            ) as mock_llm:
                with patch(
                    "balanceai_backend.utils.journal_entry_util._extract_json",
                    return_value=llm_response,
                ):
                    extract_journal_entries_from_bank_statement_transaction(sample_transaction)

        call_kwargs = mock_llm.call_args.kwargs
        assert json.loads(call_kwargs["content"]) == sample_transaction.to_dict()

    def test_passes_merchant_cache_as_context(self, sample_transaction, sample_entry_set):
        cache = {"shell oil seattle wa": "gas"}
        llm_response = sample_entry_set.model_dump_json()
        with patch(
            "balanceai_backend.utils.journal_entry_util.load_merchant_context_cache",
            return_value=cache,
        ):
            with patch(
                "balanceai_backend.utils.journal_entry_util.anthropic_service.messages",
                return_value="{}",
            ) as mock_llm:
                with patch(
                    "balanceai_backend.utils.journal_entry_util._extract_json",
                    return_value=llm_response,
                ):
                    extract_journal_entries_from_bank_statement_transaction(sample_transaction)

        call_kwargs = mock_llm.call_args.kwargs
        assert str(cache) in call_kwargs["system_instruction"]

    def test_returns_entries_from_llm_response(self, sample_transaction, sample_entry_set):
        llm_response = sample_entry_set.model_dump_json()
        with patch(
            "balanceai_backend.utils.journal_entry_util.load_merchant_context_cache",
            return_value={},
        ):
            with patch(
                "balanceai_backend.utils.journal_entry_util.anthropic_service.messages",
                return_value="{}",
            ):
                with patch(
                    "balanceai_backend.utils.journal_entry_util._extract_json",
                    return_value=llm_response,
                ):
                    result = extract_journal_entries_from_bank_statement_transaction(
                        sample_transaction
                    )

        assert len(result) == 2
        expense = next(e for e in result if e.account == JournalAccount.ESSENTIALS_EXPENSE)
        assert expense.description == "Gas purchase at Shell."
        assert expense.category == "gas"
