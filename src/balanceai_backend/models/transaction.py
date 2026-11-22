import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from balanceai_backend.models.source_transaction import Classification


@dataclass
class Transaction:
    """One real transaction (a purchase, income, a transfer side, a refund).
    Each source's version of it (a source transaction: Plaid, receipt,
    statement) points here; journal entries are booked per transaction. For now
    each transaction has one source transaction; matching will group them
    (docs/BACKEND_IMPLEMENTATION_DECISIONS.md #19).

    The fields are merged from the source transactions (refresh_transaction):
    for each, the first source with a value, preferring the bank's record
    (Plaid, then a statement, then a receipt); the transaction date prefers the
    receipt. field_sources says which source each field came from. A saved
    transaction always has its account, amount and description, and at least
    one date: it's created and filled from its first source transaction in the
    same database transaction.

    transaction_date: when it was paid (a receipt's date, else Plaid's
    authorized_date); None if no source knows.
    posted_date: when the bank posted it; None without a bank source.
    booking_date: the date it's booked and reported under.
    category: the source's category hint, not our classification.
    classification: ours (counter account, category, counterparty, who set it,
    needs review); None until classified. Set with update_transaction.
    created_at / updated_at: set by the database when saved (UTC ISO 8601).
    """

    transaction_id: str
    account_id: str
    amount: Decimal
    description: str
    transaction_date: datetime.date | None = None
    posted_date: datetime.date | None = None
    category: str | None = None
    card_last4: str | None = None
    tax: Decimal | None = None
    tip: Decimal | None = None
    classification: Classification | None = None
    field_sources: dict[str, str] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def booking_date(self) -> datetime.date:
        """When it was paid, else when the bank posted it."""
        date = self.transaction_date or self.posted_date
        assert date is not None, f"Transaction {self.transaction_id} has no date"
        return date

    def to_dict(self) -> dict:
        return {
            "transaction_id": self.transaction_id,
            "account_id": self.account_id,
            "transaction_date": _iso(self.transaction_date),
            "posted_date": _iso(self.posted_date),
            "amount": str(self.amount),
            "description": self.description,
            "category": self.category,
            "card_last4": self.card_last4,
            "tax": _str(self.tax),
            "tip": _str(self.tip),
            "classification": self.classification.to_dict() if self.classification else None,
            "field_sources": dict(self.field_sources),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Transaction":
        return cls(
            transaction_id=d["transaction_id"],
            account_id=d["account_id"],
            transaction_date=_date(d.get("transaction_date")),
            amount=Decimal(d["amount"]),
            description=d["description"],
            posted_date=_date(d.get("posted_date")),
            category=d.get("category"),
            card_last4=d.get("card_last4"),
            tax=_decimal(d.get("tax")),
            tip=_decimal(d.get("tip")),
            classification=(
                Classification.from_dict(d["classification"]) if d.get("classification") else None
            ),
            field_sources=dict(d.get("field_sources") or {}),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )


def _iso(value: datetime.date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _date(value: str | None) -> datetime.date | None:
    return datetime.date.fromisoformat(value) if value else None


def _decimal(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None
