from dataclasses import dataclass, asdict
from decimal import Decimal
from typing import Optional

from balanceai.models.bank import Bank


@dataclass
class Account:
    id: str
    name: str
    bank: Bank
    account_type: str  # checking, savings, credit_card, investment
    balance_current: Decimal
    balance_available: Optional[Decimal] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bank"] = self.bank.value
        d["balance_current"] = str(self.balance_current)
        d["balance_available"] = str(self.balance_available) if self.balance_available else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Account":
        return cls(
            id=d["id"],
            name=d["name"],
            bank=Bank(d["bank"]),
            account_type=d["account_type"],
            balance_current=Decimal(d["balance_current"]),
            balance_available=Decimal(d["balance_available"]) if d.get("balance_available") else None,
        )
