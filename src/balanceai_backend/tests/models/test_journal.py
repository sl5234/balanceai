import datetime
from decimal import Decimal

import pytest
from balanceai_backend.models.journal import (
    COUNTERPARTY_SELF,
    GeneratedJournalEntrySet,
    GeneratedJournalLine,
    JournalAccount,
    JournalLine,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def base_entry():
    return GeneratedJournalLine(
        date=datetime.date(2026, 1, 25),
        account=JournalAccount.NON_ESSENTIALS_EXPENSE,
        description="Haircut at Rudy's.",
        debit=Decimal("25.00"),
        credit=Decimal("0.00"),
    )


# ---------------------------------------------------------------------------
# GeneratedJournalLine
# ---------------------------------------------------------------------------


class TestGeneratedJournalLine:
    def test_category_defaults_to_none(self, base_entry):
        assert base_entry.category is None

    def test_category_accepts_string(self, base_entry):
        entry = base_entry.model_copy(update={"category": "haircut"})
        assert entry.category == "haircut"

    def test_tax_defaults_to_zero(self, base_entry):
        assert base_entry.tax == Decimal(0)

    def test_tax_accepts_nonzero_value(self, base_entry):
        entry = base_entry.model_copy(update={"tax": Decimal("2.25")})
        assert entry.tax == Decimal("2.25")


# ---------------------------------------------------------------------------
# GeneratedJournalLine.to_journal_line
# ---------------------------------------------------------------------------


class TestToJournalLine:
    def test_carries_category_through(self, base_entry):
        entry = base_entry.model_copy(update={"category": "haircut"})
        assert entry.to_journal_line().category == "haircut"

    def test_carries_null_category_through(self, base_entry):
        assert base_entry.to_journal_line().category is None

    def test_carries_tax_through(self, base_entry):
        entry = base_entry.model_copy(update={"tax": Decimal("2.25")})
        assert entry.to_journal_line().tax == Decimal("2.25")

    def test_generates_nonempty_journal_line_id(self, base_entry):
        assert base_entry.to_journal_line().journal_line_id != ""


# ---------------------------------------------------------------------------
# JournalLine.to_dict
# ---------------------------------------------------------------------------


@pytest.fixture
def journal_entry():
    return JournalLine(
        journal_line_id="entry-1",
        date=datetime.date(2026, 1, 25),
        account=JournalAccount.NON_ESSENTIALS_EXPENSE,
        description="Haircut at Rudy's.",
        debit=Decimal("25.00"),
        credit=Decimal("0.00"),
        category="haircut",
        tax=Decimal("2.25"),
    )


class TestJournalLineToDict:
    def test_includes_category_when_set(self, journal_entry):
        assert journal_entry.to_dict()["category"] == "haircut"

    def test_includes_category_as_none_when_not_set(self, journal_entry):
        entry = journal_entry.model_copy(update={"category": None})
        assert entry.to_dict()["category"] is None

    def test_includes_tax_as_string(self, journal_entry):
        assert journal_entry.to_dict()["tax"] == "2.25"

    def test_includes_tax_as_zero_string_when_default(self, journal_entry):
        entry = journal_entry.model_copy(update={"tax": Decimal(0)})
        assert entry.to_dict()["tax"] == "0"


# ---------------------------------------------------------------------------
# JournalLine.from_dict
# ---------------------------------------------------------------------------


@pytest.fixture
def entry_dict():
    return {
        "journal_line_id": "entry-1",
        "date": "2026-01-25",
        "account": "non_essential_expense",
        "description": "Haircut at Rudy's.",
        "debit": "25.00",
        "credit": "0.00",
        "category": "haircut",
        "tax": "2.25",
        "counterparty": COUNTERPARTY_SELF,
    }


# ---------------------------------------------------------------------------
# GeneratedJournalEntrySet
# ---------------------------------------------------------------------------


class TestGeneratedJournalEntrySet:
    def test_accepts_balanced_entries(self, base_entry):
        cash = base_entry.model_copy(
            update={
                "account": JournalAccount.CASH,
                "debit": Decimal(0),
                "credit": Decimal("25.00"),
            }
        )
        result = GeneratedJournalEntrySet(lines=[base_entry, cash])
        assert len(result.lines) == 2

    def test_accepts_empty_entries(self):
        result = GeneratedJournalEntrySet(lines=[])
        assert result.lines == []

    def test_rejects_unbalanced_entries(self, base_entry):
        with pytest.raises(ValueError, match="not balanced"):
            GeneratedJournalEntrySet(lines=[base_entry])


# ---------------------------------------------------------------------------
# JournalLine.from_dict
# ---------------------------------------------------------------------------


class TestJournalLineFromDict:
    def test_restores_category(self, entry_dict):
        assert JournalLine.from_dict(entry_dict).category == "haircut"

    def test_defaults_category_to_none_when_missing(self, entry_dict):
        del entry_dict["category"]
        assert JournalLine.from_dict(entry_dict).category is None

    def test_restores_tax(self, entry_dict):
        assert JournalLine.from_dict(entry_dict).tax == Decimal("2.25")

    def test_defaults_tax_to_zero_when_missing(self, entry_dict):
        del entry_dict["tax"]
        assert JournalLine.from_dict(entry_dict).tax == Decimal(0)
