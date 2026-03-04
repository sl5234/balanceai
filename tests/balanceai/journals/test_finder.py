import datetime
import json
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

# anthropic is not installed in the test environment — stub it out so that
# balanceai.services.anthropic_service can be imported and patched.
sys.modules.setdefault("anthropic", MagicMock())

import pytest

from balanceai.journals.finder import find_journal_entry, _strip_fences
from balanceai.models.journal import JournalAccount, JournalEntry


@pytest.fixture
def candidate():
    return JournalEntry(
        journal_entry_id="candidate-1",
        date=datetime.date(2026, 1, 27),
        account=JournalAccount.CASH,
        description="Trader Joe's purchase",
        debit=Decimal("32.02"),
        credit=Decimal("0.00"),
    )


@pytest.fixture
def existing():
    return JournalEntry(
        journal_entry_id="existing-1",
        date=datetime.date(2026, 1, 27),
        account=JournalAccount.CASH,
        description="TRADER JOES #132",
        debit=Decimal("32.00"),
        credit=Decimal("0.00"),
    )


def _llm_response(match: bool, journal_entry_id: str | None) -> str:
    return json.dumps({"match": match, "journal_entry_id": journal_entry_id})


# ---------------------------------------------------------------------------
# Short-circuit: no LLM call needed
# ---------------------------------------------------------------------------


class TestFindJournalEntryNoLlm:
    def test_returns_none_when_no_entries_for_date(self, candidate):
        with patch("balanceai.journals.finder.load_journal_entries", return_value=[]):
            result = find_journal_entry("journal-1", candidate)
        assert result is None

    def test_returns_none_when_no_entries_match_account(self, candidate):
        different_account_entry = JournalEntry(
            journal_entry_id="other-1",
            date=candidate.date,
            account=JournalAccount.NON_ESSENTIALS_EXPENSE,
            description="Some equipment",
            debit=Decimal("32.02"),
            credit=Decimal("0.00"),
        )
        with patch("balanceai.journals.finder.load_journal_entries", return_value=[different_account_entry]):
            result = find_journal_entry("journal-1", candidate)
        assert result is None

    def test_does_not_call_llm_when_no_candidates(self, candidate):
        with patch("balanceai.journals.finder.load_journal_entries", return_value=[]):
            with patch("balanceai.services.anthropic.messages") as mock_llm:
                find_journal_entry("journal-1", candidate)
        mock_llm.assert_not_called()


# ---------------------------------------------------------------------------
# LLM matching
# ---------------------------------------------------------------------------


class TestFindJournalEntryWithLlm:
    def test_returns_matching_entry_when_llm_finds_match(self, candidate, existing):
        with patch("balanceai.journals.finder.load_journal_entries", return_value=[existing]):
            with patch("balanceai.services.anthropic.messages") as mock_llm:
                mock_llm.return_value = _llm_response(True, existing.journal_entry_id)
                result = find_journal_entry("journal-1", candidate)
        assert result is existing

    def test_returns_none_when_llm_finds_no_match(self, candidate, existing):
        with patch("balanceai.journals.finder.load_journal_entries", return_value=[existing]):
            with patch("balanceai.services.anthropic.messages") as mock_llm:
                mock_llm.return_value = _llm_response(False, None)
                result = find_journal_entry("journal-1", candidate)
        assert result is None

    def test_returns_none_when_llm_returns_unknown_id(self, candidate, existing):
        with patch("balanceai.journals.finder.load_journal_entries", return_value=[existing]):
            with patch("balanceai.services.anthropic.messages") as mock_llm:
                mock_llm.return_value = _llm_response(True, "nonexistent-id")
                result = find_journal_entry("journal-1", candidate)
        assert result is None

    def test_llm_called_with_correct_model(self, candidate, existing):
        with patch("balanceai.journals.finder.load_journal_entries", return_value=[existing]):
            with patch("balanceai.services.anthropic.messages") as mock_llm:
                mock_llm.return_value = _llm_response(False, None)
                find_journal_entry("journal-1", candidate)
        assert mock_llm.call_args.kwargs["model_id"] == "claude-haiku-4-5-20251001"
        assert mock_llm.call_args.kwargs["temperature"] == 0.0

    def test_llm_response_with_code_fences_is_handled(self, candidate, existing):
        fenced = f"```json\n{_llm_response(True, existing.journal_entry_id)}\n```"
        with patch("balanceai.journals.finder.load_journal_entries", return_value=[existing]):
            with patch("balanceai.services.anthropic.messages") as mock_llm:
                mock_llm.return_value = fenced
                result = find_journal_entry("journal-1", candidate)
        assert result is existing


# ---------------------------------------------------------------------------
# _strip_fences
# ---------------------------------------------------------------------------


class TestStripFences:
    def test_strips_json_code_fence(self):
        assert _strip_fences("```json\n{}\n```") == "{}"

    def test_strips_plain_code_fence(self):
        assert _strip_fences("```\n{}\n```") == "{}"

    def test_leaves_plain_json_unchanged(self):
        assert _strip_fences('{"match": false}') == '{"match": false}'

    def test_strips_surrounding_whitespace(self):
        assert _strip_fences("  {}\n  ") == "{}"
