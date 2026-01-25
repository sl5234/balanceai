from dataclasses import dataclass, asdict

from balanceai.models.bank import Bank


@dataclass
class Account:
    id: str  # account number
    bank: Bank
    account_type: str  # checking, savings, credit_card, investment

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bank"] = self.bank.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Account":
        return cls(
            id=d["id"],
            bank=Bank(d["bank"]),
            account_type=d["account_type"],
        )
