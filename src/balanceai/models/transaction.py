from dataclasses import dataclass, asdict
from datetime import date
from decimal import Decimal
from hashlib import sha256
from typing import Optional


@dataclass
class Transaction:
    id: str
    account_id: str
    date: date
    description: str
    amount: Decimal  # negative = debit, positive = credit
    category: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        d["amount"] = str(self.amount)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Transaction":
        return cls(
            id=d["id"],
            account_id=d["account_id"],
            date=date.fromisoformat(d["date"]),
            description=d["description"],
            amount=Decimal(d["amount"]),
            category=d.get("category"),
        )

    @staticmethod
    def generate_id(account_id: str, txn_date: date, description: str, amount: Decimal) -> str:
        raw = f"{account_id}|{txn_date.isoformat()}|{description}|{amount}"
        return sha256(raw.encode()).hexdigest()[:16]
