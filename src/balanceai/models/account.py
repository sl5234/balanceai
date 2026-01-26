from dataclasses import dataclass, asdict
from enum import Enum

from balanceai.models.bank import Bank


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

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bank"] = self.bank.value
        d["account_type"] = self.account_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Account":
        return cls(
            id=d["id"],
            bank=Bank(d["bank"]),
            account_type=AccountType(d["account_type"]),
        )
