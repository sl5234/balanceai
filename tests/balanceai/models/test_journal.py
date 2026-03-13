import datetime
from decimal import Decimal

import pytest

from balanceai.models.journal import (
    GeneratedJournalEntry,
    JournalAccount,
    JournalEntry,
    RECIPIENT_SELF,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def base_entry():
    return GeneratedJournalEntry(
        date=datetime.date(2026, 1, 25),
        account=JournalAccount.NON_ESSENTIALS_EXPENSE,
        description="Haircut at Rudy's.",
        debit=Decimal("25.00"),
        credit=Decimal("0.00"),
    )


# ---------------------------------------------------------------------------
# GeneratedJournalEntry
# ---------------------------------------------------------------------------


class TestGeneratedJournalEntry:
    def test_category_defaults_to_none(self, base_entry):
        assert base_entry.category is None

    def test_category_accepts_string(self, base_entry):
        entry = base_entry.model_copy(update={"category": "haircut"})
        assert entry.category == "haircut"

    def test_tax_defaults_to_zero(self, base_entry):
        assert base_entry.tax == Decimal("0")

    def test_tax_accepts_nonzero_value(self, base_entry):
        entry = base_entry.model_copy(update={"tax": Decimal("2.25")})
        assert entry.tax == Decimal("2.25")


# ---------------------------------------------------------------------------
# GeneratedJournalEntry.to_journal_entry
# ---------------------------------------------------------------------------


class TestToJournalEntry:
    def test_carries_category_through(self, base_entry):
        entry = base_entry.model_copy(update={"category": "haircut"})
        assert entry.to_journal_entry().category == "haircut"

    def test_carries_null_category_through(self, base_entry):
        assert base_entry.to_journal_entry().category is None

    def test_carries_tax_through(self, base_entry):
        entry = base_entry.model_copy(update={"tax": Decimal("2.25")})
        assert entry.to_journal_entry().tax == Decimal("2.25")

    def test_generates_nonempty_journal_entry_id(self, base_entry):
        assert base_entry.to_journal_entry().journal_entry_id != ""


# ---------------------------------------------------------------------------
# JournalEntry.to_dict
# ---------------------------------------------------------------------------


@pytest.fixture
def journal_entry():
    return JournalEntry(
        journal_entry_id="entry-1",
        date=datetime.date(2026, 1, 25),
        account=JournalAccount.NON_ESSENTIALS_EXPENSE,
        description="Haircut at Rudy's.",
        debit=Decimal("25.00"),
        credit=Decimal("0.00"),
        category="haircut",
        tax=Decimal("2.25"),
    )


class TestJournalEntryToDict:
    def test_includes_category_when_set(self, journal_entry):
        assert journal_entry.to_dict()["category"] == "haircut"

    def test_includes_category_as_none_when_not_set(self, journal_entry):
        entry = journal_entry.model_copy(update={"category": None})
        assert entry.to_dict()["category"] is None

    def test_includes_tax_as_string(self, journal_entry):
        assert journal_entry.to_dict()["tax"] == "2.25"

    def test_includes_tax_as_zero_string_when_default(self, journal_entry):
        entry = journal_entry.model_copy(update={"tax": Decimal("0")})
        assert entry.to_dict()["tax"] == "0"


# ---------------------------------------------------------------------------
# JournalEntry.from_dict
# ---------------------------------------------------------------------------


@pytest.fixture
def entry_dict():
    return {
        "journal_entry_id": "entry-1",
        "date": "2026-01-25",
        "account": "non_essential_expense",
        "description": "Haircut at Rudy's.",
        "debit": "25.00",
        "credit": "0.00",
        "category": "haircut",
        "tax": "2.25",
        "recipient": RECIPIENT_SELF,
    }


class TestJournalEntryFromDict:
    def test_restores_category(self, entry_dict):
        assert JournalEntry.from_dict(entry_dict).category == "haircut"

    def test_defaults_category_to_none_when_missing(self, entry_dict):
        del entry_dict["category"]
        assert JournalEntry.from_dict(entry_dict).category is None

    def test_restores_tax(self, entry_dict):
        assert JournalEntry.from_dict(entry_dict).tax == Decimal("2.25")

    def test_defaults_tax_to_zero_when_missing(self, entry_dict):
        del entry_dict["tax"]
        assert JournalEntry.from_dict(entry_dict).tax == Decimal("0")
