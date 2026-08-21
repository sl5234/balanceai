import datetime
from dataclasses import asdict, dataclass
from decimal import Decimal


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

    account_id: for Plaid, this is Plaid's own raw account id (the mapping to
    our Account.id is deferred — see PLAID_INTEGRATION_DECISIONS.md). For
    receipt/bank-statement sources, this should be our actual Account.id
    directly, since those sources already know which of our accounts a
    transaction belongs to — no Plaid-account-mapping ambiguity there. That
    means the same column means something different depending on `source`,
    at least until the Plaid account-mapping work lands.

    plaid_item_id: only set when source == "plaid" — nullable so
    receipt/bank-statement rows (which have no Plaid item at all) aren't
    forced to fake one.
    """

    id: str
    source: str  # "plaid" | "receipt" | "bank_statement"
    account_id: str
    posting_date: datetime.date
    description: str
    amount: Decimal  # negative = debit, positive = credit — flipped from Plaid's own convention
    plaid_item_id: str | None = None
    category: str | None = None
    pending: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["posting_date"] = self.posting_date.isoformat()
        d["amount"] = str(self.amount)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RawTransaction":
        return cls(
            id=d["id"],
            source=d["source"],
            plaid_item_id=d.get("plaid_item_id"),
            account_id=d["account_id"],
            posting_date=datetime.date.fromisoformat(d["posting_date"]),
            description=d["description"],
            amount=Decimal(d["amount"]),
            category=d.get("category"),
            pending=bool(d.get("pending", False)),
        )
