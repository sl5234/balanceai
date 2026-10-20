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
    RawTransaction is what its source said. Journal entries are generated from
    this by rule; see docs/BACKEND_IMPLEMENTATION_DECISIONS.md #2.

    counter_account: the account on the other side of the entry from the bank
    account itself — e.g. non_essential_expense for a dinner, sales for a salary.

    classified_by: who set this. A classification set by the user is never
    replaced by the AI.

    needs_user_review: the source changed something about the transaction
    after the user classified it, so the user should check it still holds.
    Cleared when the classification is set again.
    """

    counter_account: JournalAccount
    classified_by: ClassifiedBy
    category: str | None = None
    counterparty: str | None = None
    needs_user_review: bool = False

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
class RawTransaction:
    """A transaction before it's turned into journal entries, from any source
    (Plaid, receipt OCR, bank statement parsing). Unlike Transaction (built
    specifically for bank-statement PDFs, which print a running balance line
    by line), there's no previous_balance/new_balance here — not every source
    has that concept, so it's left out entirely rather than made nullable.

    id: for Plaid, this is Plaid's own transaction_id (not our hash-based
    Transaction.generate_id — it needs to stay stable across
    added -> modified -> removed for the same real-world transaction, which a
    content hash wouldn't survive once a field like amount changes). Other
    sources should use whatever stable identifier makes sense for them.

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

    classification: None until the transaction has been classified.
    """

    id: str
    source: str  # "plaid" | "receipt" | "bank_statement"
    account_id: str
    posting_date: datetime.date
    description: str
    amount: Decimal  # negative = debit, positive = credit — flipped from Plaid's own convention
    plaid_item_id: str | None = None
    plaid_account_id: str | None = None
    category: str | None = None
    category_detailed: str | None = None
    category_confidence: str | None = None
    pending: bool = False
    classification: Classification | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["posting_date"] = self.posting_date.isoformat()
        d["amount"] = str(self.amount)
        d["classification"] = self.classification.to_dict() if self.classification else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RawTransaction":
        return cls(
            id=d["id"],
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
            classification=(
                Classification.from_dict(d["classification"]) if d.get("classification") else None
            ),
        )
