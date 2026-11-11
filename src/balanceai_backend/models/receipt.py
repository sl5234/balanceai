from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class PaymentMethod(StrEnum):
    CARD = "card"
    CASH = "cash"
    UNKNOWN = "unknown"


class ReceiptKind(StrEnum):
    PURCHASE = "purchase"  # money out (also bills, paying a person, donations)
    REFUND = "refund"  # money back, e.g. a return slip


class ReceiptExtraction(BaseModel):
    """What a receipt image says, read by the AI. Booking turns it into journal
    lines by rule, never the AI (docs/BACKEND_IMPLEMENTATION_DECISIONS.md #18)."""

    date: date
    counterparty: str = Field(
        description="Who was paid or who refunded: a store, company or person, "
        "e.g. 'Blue Bottle Coffee'"
    )
    kind: ReceiptKind = Field(description="purchase (money out) or refund (money back)")
    total: Decimal = Field(
        description="Amount paid or refunded, as a positive number, including tax and "
        "tip if printed"
    )
    tax: Decimal | None = Field(None, description="Tax, if printed")
    tip: Decimal | None = Field(None, description="Tip, if printed")
    payment_method: PaymentMethod
    card_last4: str | None = Field(None, description="Last 4 digits of the card, if printed")
    items: list[str] = Field(
        default_factory=list,
        description="Item names as printed, e.g. ['Milk', 'Bread']. Not stored.",
    )
    category: str | None = Field(
        None,
        description="What the purchase was for, judged from the counterparty and items, "
        "e.g. 'groceries' or 'dining'",
    )


class AccountMatch(StrEnum):
    """How a receipt's paying account was found."""

    CASH = "cash"  # the journal's cash account
    HISTORY = "history"  # an earlier receipt with the same card
    LAST4 = "last4"  # a bank account whose own last 4 matches the card
    USER = "user"  # the user passed account_id


@dataclass
class ReceiptAccount:
    """The account that paid for a receipt, and how it was found."""

    account_id: str
    match: AccountMatch
