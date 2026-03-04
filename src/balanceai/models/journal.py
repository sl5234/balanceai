import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path

from appdevcommons.unique_id import UniqueIdGenerator
from pydantic import BaseModel, Field

from balanceai.models.account import Account


class JournalAccount(str, Enum):
    CASH = "cash"
    ACCOUNTS_PAYABLE = "accounts_payable"
    ACCOUNTS_RECEIVABLE = "accounts_receivable"
    RENT = "rent"
    ESSENTIALS_EXPENSE = "essential_expense"
    NON_ESSENTIALS_EXPENSE = "non_essential_expense"
    SALES = "sales"


class JournalEntryData(BaseModel):
    """JournalEntry fields without the entry ID. Used as the output format for OCR extraction."""

    date: datetime.date
    account: JournalAccount = Field(
        description=(
            "The account type for this entry. Use 'cash' for point-of-sale or cash purchases. "
            "Use 'accounts_payable' for bills owed to vendors. "
            "Use 'accounts_receivable' for money owed to you. "
            "Use 'rent' for rent payments. "
            "Use 'essential_expense' for necessary expenses like groceries (specifically, meat, vegetables, dog food), car insurance, books, gas, hospital visits, haircuts. "
            "Use 'essential_expense' for non-essential expenses like groceries (snacks, fruits, dog treats), dining, cigarettes, vet visits, parking, etc. "
            "Use 'sales' for revenue transactions like income. "
        )
    )
    description: str = Field(
        description=(
            "Briefly describe the transaction. Include only enough information to accurately "
            "remind you where the money came from or why it was spent. "
            "Examples: 'Loan from Liberty Bank.', 'Tax return from IRS.', "
            "'Grocery purchase from Trader Joe's.', 'Repairs for car windshield from Chuck's repair shop.'"
        )
    )
    debit: Decimal
    credit: Decimal

    def to_journal_entry(self) -> "JournalEntry":
        return JournalEntry(
            journal_entry_id=UniqueIdGenerator.generate_id(),
            date=self.date,
            account=self.account,
            description=self.description,
            debit=self.debit,
            credit=self.credit,
        )


class JournalEntryDataSet(BaseModel):
    entries: list[JournalEntryData] = Field(
        description=(
            "The journal entries for this transaction. "
            "Use double-entry bookkeeping: each transaction should have at least two entries "
            "where debits equal credits."
        )
    )


class ReceiptInputConfig(BaseModel):
    input_local_path: Path


class PlaidTransactionInputConfig(BaseModel):
    transactions: dict



@dataclass
class JournalEntry:
    journal_entry_id: str
    date: datetime.date
    account: JournalAccount
    description: str
    debit: Decimal
    credit: Decimal
    tax: Decimal = Decimal("0")

    def to_dict(self) -> dict:
        return {
            "journal_entry_id": self.journal_entry_id,
            "date": self.date.isoformat(),
            "account": self.account.value,
            "description": self.description,
            "debit": str(self.debit),
            "credit": str(self.credit),
            "tax": str(self.tax),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "JournalEntry":
        return cls(
            journal_entry_id=d["journal_entry_id"],
            date=datetime.date.fromisoformat(d["date"]),
            account=JournalAccount(d["account"]),
            description=d["description"],
            debit=Decimal(d["debit"]),
            credit=Decimal(d["credit"]),
            tax=Decimal(d.get("tax", "0")),
        )


@dataclass
class Journal:
    account: Account
    description: str
    start_date: datetime.date
    end_date: datetime.date
    journal_id: str = field(default_factory=UniqueIdGenerator.generate_id)
    entries: list[JournalEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "journal_id": self.journal_id,
            "account": self.account.to_dict(),
            "description": self.description,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "entries": [e.to_dict() for e in self.entries],
        }

    def add_entry(self, entry: JournalEntry) -> None:
        """Add a journal entry."""
        self.entries.append(entry)

    def remove_entry(self, journal_entry_id: str) -> JournalEntry | None:
        """Remove a journal entry by its journal_entry_id. Returns the removed entry, or None if not found."""
        for i, entry in enumerate(self.entries):
            if entry.journal_entry_id == journal_entry_id:
                return self.entries.pop(i)
        return None

    @classmethod
    def from_dict(cls, d: dict) -> "Journal":
        return cls(
            account=Account.from_dict(d["account"]),
            description=d.get("description", ""),
            start_date=datetime.date.fromisoformat(d["start_date"]),
            end_date=datetime.date.fromisoformat(d["end_date"]),
            journal_id=d.get("journal_id", UniqueIdGenerator.generate_id()),
            entries=[JournalEntry.from_dict(e) for e in d.get("entries", [])],
        )
