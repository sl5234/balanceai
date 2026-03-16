import bisect
import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path

from appdevcommons.unique_id import UniqueIdGenerator
from pydantic import BaseModel, Field, model_validator

from balanceai_backend.models.account import Account


class JournalAccount(str, Enum):
    CASH = "cash"
    ACCOUNTS_PAYABLE = "accounts_payable"
    ACCOUNTS_RECEIVABLE = "accounts_receivable"
    RENT = "rent"
    ESSENTIALS_EXPENSE = "essential_expense"
    NON_ESSENTIALS_EXPENSE = "non_essential_expense"
    SALES = "sales"
    INVESTMENTS = "investments"


RECIPIENT_SELF = "Self"


class GeneratedJournalEntry(BaseModel):
    """JournalEntry fields without the entry ID. Used as the output format for OCR extraction."""

    date: datetime.date
    account: JournalAccount = Field(
        description=(
            "The account type for this entry. "
            "Use 'cash' as the offsetting account representing the bank or cash balance (e.g. the credit side of an expense, or the debit side of income). "
            "Use 'accounts_payable' for bills owed to vendors. "
            "Use 'accounts_receivable' for money owed to you. "
            "Use 'rent' for rent payments. "
            "Use 'essential_expense' for necessary expenses like groceries (specifically, meat, vegetables, dog food), car insurance, books, gas, hospital visits, internet expenses, anthropic subscription, etc. "
            "Use 'non_essential_expense' for non-essential expenses like groceries (snacks, fruits, dog treats), dining, cigarettes, vet visits, parking, haircuts, etc. "
            "Use 'sales' for revenue transactions like income. "
            "Use 'investments' for investments. "
            "If you cannot clearly determine the nature of the business from its name or the provided context, "
            "default to 'non_essential_expense'."
        )
    )
    description: str = Field(
        description=(
            "Briefly describe the transaction. Include only enough information to accurately "
            "remind you where the money came from or why it was spent. "
            "Only describe what you can clearly infer — if the nature of the transaction is unclear "
            "(e.g. the merchant name is ambiguous or the purpose cannot be determined), "
            "use 'Uncategorized transaction from X' where X is the merchant or payee name. "
            "Never guess or infer the type of business from the name alone. "
            "For example, 'Rudy's' should be described as 'Uncategorized transaction from Rudy\\'s', "
            "not 'Dining at Rudy\\'s' or 'Haircut at Rudy\\'s'."
            "For refunds: if a money comes in (positive amount instead of negative amount) from a known "
            "retailer or merchant (e.g., Amazon, Walmart, a restaurant), treat it as a refund. For a refund, "
            "just reverse what the original purchase would have used."
        ),
        examples=[
            "Loan from Liberty Bank.",
            "Tax return from IRS.",
            "Grocery purchase from Trader Joe's.",
            "Repairs for car windshield from Chuck's repair shop.",
            "Refund from Amazon.com.",
            "Uncategorized transaction from Rudy's.",
            "Uncategorized transaction from District-H.",
        ],
    )
    debit: Decimal
    credit: Decimal
    category: str | None = Field(
        default=None,
        description=(
            "A short category label for this transaction. "
            "Set to null only when the merchant is truly ambiguous and cannot be determined from the description alone."
        ),
        examples=[
            "dining",
            "groceries",
            "gas",
            "rideshare",
            "subscription",
            "transfer",
            "rent",
            "utilities",
            "insurance",
            "entertainment",
            "travel",
            "healthcare",
            "income",
        ],
    )
    tax: Decimal = Field(
        default=Decimal("0"),
        description=(
            "Sales tax or VAT included in this transaction, if any. "
            "Default to 0 if unknown or not applicable."
        ),
    )
    recipient: str = Field(
        default=RECIPIENT_SELF,
        description=(
            "Who received the value in this entry. "
            "For the expense/asset debit entry, use 'Self' (you are the one incurring the expense). "
            "For the cash/offsetting credit entry, use the merchant or payee name (they received the money). "
            "For income entries, use 'Self' on the debit (cash) side and the payer name on the credit (sales) side."
        ),
    )

    def to_journal_entry(self) -> "JournalEntry":
        return JournalEntry(
            journal_entry_id=UniqueIdGenerator.generate_id(),
            **self.model_dump(),
        )


class GeneratedJournalEntrySet(BaseModel):
    entries: list[GeneratedJournalEntry] = Field(
        description=(
            "The journal entries for this transaction. "
            "Use double-entry bookkeeping: each transaction should have at least two entries "
            "where debits equal credits."
        )
    )

    @model_validator(mode="after")
    def validate_balanced(self) -> "GeneratedJournalEntrySet":
        total_debit = sum(e.debit for e in self.entries)
        total_credit = sum(e.credit for e in self.entries)
        if total_debit != total_credit:
            raise ValueError(
                f"Journal entries are not balanced: total debit {total_debit} != total credit {total_credit}"
            )
        return self


class ReceiptInputConfig(BaseModel):
    input_local_path: Path


class PlaidTransactionInputConfig(BaseModel):
    transactions: dict



class JournalEntry(GeneratedJournalEntry):
    journal_entry_id: str

    def __lt__(self, other: "JournalEntry") -> bool:
        return self.date < other.date

    def to_dict(self, redact: bool = False) -> dict:
        return {
            "journal_entry_id": self.journal_entry_id,
            "date": self.date.isoformat(),
            "account": self.account.value,
            "description": None if redact else self.description,
            "debit": str(self.debit),
            "credit": str(self.credit),
            "category": None if redact else self.category,
            "tax": str(self.tax),
            "recipient": None if redact else self.recipient,
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
            category=d.get("category"),
            tax=Decimal(d.get("tax", "0")),
            recipient=d.get("recipient", RECIPIENT_SELF),
        )


@dataclass
class Journal:
    account: Account
    description: str
    start_date: datetime.date
    end_date: datetime.date
    journal_id: str = field(default_factory=UniqueIdGenerator.generate_id)
    entries: list[JournalEntry] = field(default_factory=list)

    def to_dict(self, redact_entries: bool = False) -> dict:
        return {
            "journal_id": self.journal_id,
            "account": self.account.to_dict(),
            "description": self.description,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "entries": [] if redact_entries else [e.to_dict() for e in self.entries],
        }

    def add_entry(self, entry: JournalEntry) -> None:
        """Add a journal entry, maintaining sort order by date."""
        bisect.insort(self.entries, entry)

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
