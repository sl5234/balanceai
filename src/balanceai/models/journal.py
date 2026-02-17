import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from appdevcommons.unique_id import UniqueIdGenerator

from balanceai.models.account import Account


class JournalAccount(str, Enum):
    CASH = "cash"
    ACCOUNTS_PAYABLE = "accounts_payable"
    ACCOUNTS_RECEIVABLE = "accounts_receivable"
    GENERAL = "general"
    SALES = "sales"
    EQUIPMENT = "equipment"
    WAGE = "wage"
    LAND = "land"


@dataclass
class JournalEntryInputConfig:
    input_local_path: str

    def to_dict(self) -> dict:
        return {"input_local_path": self.input_local_path}

    @classmethod
    def from_dict(cls, d: dict) -> "JournalEntryInputConfig":
        return cls(input_local_path=d["input_local_path"])


@dataclass
class JournalEntry:
    journal_entry_id: str
    date: datetime.date
    account: JournalAccount
    description: str
    debit: Decimal
    credit: Decimal

    def to_dict(self) -> dict:
        return {
            "journal_entry_id": self.journal_entry_id,
            "date": self.date.isoformat(),
            "account": self.account.value,
            "description": self.description,
            "debit": str(self.debit),
            "credit": str(self.credit),
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
