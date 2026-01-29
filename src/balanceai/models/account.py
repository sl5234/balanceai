from dataclasses import dataclass, asdict, field
from decimal import Decimal
from enum import Enum
from typing import Optional

from balanceai.models.bank import Bank
from balanceai.models.category import Category


class AccountType(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"
    SAVING = "saving"
    INVESTMENT = "investment"


@dataclass
class Account:
    id: str  # hashed account number
    bank: Bank
    account_type: AccountType
    balance: Optional[Decimal] = None
    categories: list[Category] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bank"] = self.bank.value
        d["account_type"] = self.account_type.value
        d["balance"] = str(self.balance) if self.balance is not None else None
        d["categories"] = [c.to_dict() for c in self.categories]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Account":
        balance = d.get("balance")
        return cls(
            id=d["id"],
            bank=Bank(d["bank"]),
            account_type=AccountType(d["account_type"]),
            balance=Decimal(balance) if balance is not None else None,
            categories=[Category.from_dict(c) for c in d.get("categories", [])],
        )
