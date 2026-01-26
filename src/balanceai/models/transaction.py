from dataclasses import dataclass, asdict
import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Optional


@dataclass
class Transaction:
    id: str
    account_id: str
    date: datetime.date
    description: str
    amount: Decimal  # negative = debit, positive = credit
    previous_balance: Decimal
    new_balance: Decimal
    category: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        d["amount"] = str(self.amount)
        d["previous_balance"] = str(self.previous_balance)
        d["new_balance"] = str(self.new_balance)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Transaction":
        return cls(
            id=d["id"],
            account_id=d["account_id"],
            date=datetime.date.fromisoformat(d["date"]),
            description=d["description"],
            amount=Decimal(d["amount"]),
            previous_balance=Decimal(d["previous_balance"]),
            new_balance=Decimal(d["new_balance"]),
            category=d.get("category"),
        )

    def __lt__(self, other: "Transaction") -> bool:
        """Enable sorting by date."""
        return self.date < other.date

    @staticmethod
    def generate_id(account_id: str, txn_date: datetime.date, description: str, amount: Decimal) -> str:
        raw = f"{account_id}|{txn_date.isoformat()}|{description}|{amount}"
        return sha256(raw.encode()).hexdigest()[:16]
