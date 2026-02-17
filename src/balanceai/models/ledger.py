import datetime
from dataclasses import dataclass
from decimal import Decimal

from balanceai.models.journal import JournalAccount


@dataclass
class AccountLedger:
    account: JournalAccount
    date: datetime.date
    credit: Decimal
    debit: Decimal
    balance: Decimal

    def to_dict(self) -> dict:
        return {
            "account": self.account.value,
            "date": self.date.isoformat(),
            "credit": str(self.credit),
            "debit": str(self.debit),
            "balance": str(self.balance),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AccountLedger":
        return cls(
            account=JournalAccount(d["account"]),
            date=datetime.date.fromisoformat(d["date"]),
            credit=Decimal(d["credit"]),
            debit=Decimal(d["debit"]),
            balance=Decimal(d["balance"]),
        )
