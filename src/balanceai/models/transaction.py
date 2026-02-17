from dataclasses import dataclass, asdict
import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Optional


@dataclass
class Transaction:
    id: str
    account_id: str
    posting_date: datetime.date
    description: str
    amount: Decimal  # negative = debit, positive = credit
    previous_balance: Decimal
    new_balance: Decimal
    category: Optional[str] = None
    transaction_date: Optional[datetime.date] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["posting_date"] = self.posting_date.isoformat()
        d["transaction_date"] = self.transaction_date.isoformat() if self.transaction_date else None
        d["amount"] = str(self.amount)
        d["previous_balance"] = str(self.previous_balance)
        d["new_balance"] = str(self.new_balance)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Transaction":
        txn_date_str = d.get("transaction_date")
        return cls(
            id=d["id"],
            account_id=d["account_id"],
            posting_date=datetime.date.fromisoformat(d["posting_date"]),
            description=d["description"],
            amount=Decimal(d["amount"]),
            previous_balance=Decimal(d["previous_balance"]),
            new_balance=Decimal(d["new_balance"]),
            category=d.get("category"),
            transaction_date=datetime.date.fromisoformat(txn_date_str) if txn_date_str else None,
        )

    def __lt__(self, other: "Transaction") -> bool:
        """Enable sorting by posting date."""
        return self.posting_date < other.posting_date

    @staticmethod
    def generate_id(
        account_id: str, txn_date: datetime.date, description: str, amount: Decimal
    ) -> str:
        raw = f"{account_id}|{txn_date.isoformat()}|{description}|{amount}"
        return sha256(raw.encode()).hexdigest()[:16]
