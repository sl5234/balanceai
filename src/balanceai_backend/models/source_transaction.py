import datetime
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import Enum

from balanceai_backend.models.journal import JournalAccount


class ClassifiedBy(str, Enum):
    AI = "ai"
    USER = "user"


@dataclass
class Classification:
    """Our judgment of what a transaction is — everything else on a
    SourceTransaction is what its source said. Journal entries are generated from
    this by rule; see docs/BACKEND_IMPLEMENTATION_DECISIONS.md #2.

    counter_account: the account on the other side of the entry from the bank
    account itself — e.g. non_essential_expense for a dinner, sales for a salary.

    classified_by: who set this. A classification set by the user is never
    replaced by the AI.

    needs_user_review: a person should check this classification — the source
    changed the transaction after the user classified it, or the AI couldn't
    tell what it was for (no category, or counter_account unclassified, which
    always sets it). Cleared when the classification is set again.
    """

    counter_account: JournalAccount
    classified_by: ClassifiedBy
    category: str | None = None
    counterparty: str | None = None
    needs_user_review: bool = False

    def __post_init__(self) -> None:
        # An unknown purpose always needs a person, whoever classified it.
        if self.counter_account == JournalAccount.UNCLASSIFIED:
            self.needs_user_review = True

    def to_dict(self) -> dict:
        return {
            "counter_account": self.counter_account.value,
            "category": self.category,
            "counterparty": self.counterparty,
            "classified_by": self.classified_by.value,
            "needs_user_review": self.needs_user_review,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Classification":
        return cls(
            counter_account=JournalAccount(d["counter_account"]),
            category=d.get("category"),
            counterparty=d.get("counterparty"),
            classified_by=ClassifiedBy(d["classified_by"]),
            needs_user_review=bool(d.get("needs_user_review", False)),
        )


@dataclass
class SourceTransaction:
    """A transaction before it's turned into journal entries, from any source
    (Plaid, receipt OCR, bank statement parsing). Unlike Transaction (built
    specifically for bank-statement PDFs, which print a running balance line
    by line), there's no previous_balance/new_balance here — not every source
    has that concept, so it's left out entirely rather than made nullable.

    source_transaction_id: ours, prefixed by source ('plaid-…', 'receipt-…';
    utils.general_util.generate_id), and never changes;
    journal_lines.source_transaction_id points at it. When saving a Plaid row
    that already exists (same plaid_transaction_id), the stored id is kept
    instead.

    plaid_transaction_id: Plaid's own transaction_id, stable across
    added -> modified -> removed; Plaid sync finds rows by it. None for other
    sources. A re-link issues new ones for the same purchases (BL-5).

    account_id: our BankAccount id, for every source. Plaid transactions are
    mapped from Plaid's own account id to it at sync time.

    plaid_account_id: Plaid's own account id, kept alongside account_id for
    Plaid rows (None for other sources).

    plaid_item_id: only set when source == "plaid" — nullable so
    receipt/bank-statement rows (which have no Plaid item at all) aren't
    forced to fake one. Also cleared (the row itself is kept) if that Plaid
    item is later unlinked.

    category: the source's own category (e.g. Plaid's), not ours — ours is in
    classification.

    category_detailed / category_confidence: the source's finer category and
    how sure the source is of it (Plaid: personal_finance_category.detailed and
    .confidence_level, e.g. "FOOD_AND_DRINK_RESTAURANT" / "LOW"). None for
    sources that don't provide them.

    card_last4 / tax / tip: from a receipt (None for other sources). card_last4
    is the card printed on it, used to find the paying account for later
    receipts on the same card (BACKEND_IMPLEMENTATION_DECISIONS #18).

    Our classification isn't here: it's the transaction's (Transaction.classification).

    transaction_id: the transaction this belongs to; set when first saved, then
    never changes.

    created_at / updated_at: set by the database when saved (UTC ISO 8601);
    ignored when saving.
    """

    source_transaction_id: str
    source: str  # "plaid" | "receipt" | "bank_statement"
    account_id: str
    posting_date: datetime.date
    description: str
    # Required of every source (Plaid, statements, receipts): negative = money out of
    # this account, positive = money in. On a credit card, a charge is negative and a
    # payment or refund is positive. Plaid's sign is the opposite, so sync flips it;
    # a statement or receipt parser must convert to this before storing.
    amount: Decimal
    plaid_item_id: str | None = None
    plaid_account_id: str | None = None
    category: str | None = None
    category_detailed: str | None = None
    category_confidence: str | None = None
    pending: bool = False
    card_last4: str | None = None
    tax: Decimal | None = None
    tip: Decimal | None = None
    plaid_transaction_id: str | None = None
    transaction_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["posting_date"] = self.posting_date.isoformat()
        d["amount"] = str(self.amount)
        d["tax"] = str(self.tax) if self.tax is not None else None
        d["tip"] = str(self.tip) if self.tip is not None else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SourceTransaction":
        return cls(
            source_transaction_id=d["source_transaction_id"],
            plaid_transaction_id=d.get("plaid_transaction_id"),
            transaction_id=d.get("transaction_id"),
            source=d["source"],
            plaid_item_id=d.get("plaid_item_id"),
            plaid_account_id=d.get("plaid_account_id"),
            account_id=d["account_id"],
            posting_date=datetime.date.fromisoformat(d["posting_date"]),
            description=d["description"],
            amount=Decimal(d["amount"]),
            category=d.get("category"),
            category_detailed=d.get("category_detailed"),
            category_confidence=d.get("category_confidence"),
            pending=bool(d.get("pending", False)),
            card_last4=d.get("card_last4"),
            tax=Decimal(d["tax"]) if d.get("tax") is not None else None,
            tip=Decimal(d["tip"]) if d.get("tip") is not None else None,
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )
