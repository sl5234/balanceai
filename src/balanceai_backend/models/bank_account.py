import re
from dataclasses import asdict, dataclass
from enum import Enum


class BankAccountType(str, Enum):
    # depository (asset)
    CHECKING = "checking"
    SAVINGS = "savings"
    MONEY_MARKET = "money_market"
    CD = "cd"
    OTHER_DEPOSITORY = "other_depository"  # prepaid, cash management, ...

    # credit (liability)
    CREDIT_CARD = "credit_card"
    OTHER_CREDIT = "other_credit"  # e.g. PayPal credit

    # loan (liability)
    MORTGAGE = "mortgage"
    HOME_EQUITY = "home_equity"  # home equity loans and HELOCs
    AUTO_LOAN = "auto_loan"
    STUDENT_LOAN = "student_loan"
    PERSONAL_LOAN = "personal_loan"  # Plaid calls this "consumer"
    LINE_OF_CREDIT = "line_of_credit"
    OTHER_LOAN = "other_loan"

    # investment (asset)
    BROKERAGE = "brokerage"
    IRA = "ira"
    ROTH_IRA = "roth_ira"
    RETIREMENT_401K = "401k"
    ROTH_401K = "roth_401k"
    HSA = "hsa"
    COLLEGE_529 = "529"
    OTHER_INVESTMENT = "other_investment"


def build_bank_account_id(institution_name: str, account_type: BankAccountType, last4: str) -> str:
    """
    Build a BankAccount id: `<institution>:<account_type>:<last4>` — see
    docs/PLAID_INTEGRATION_DECISIONS.md #3. The institution name is lowercased,
    with whitespace turned into `_` and anything else non-alphanumeric dropped.

    Raises:
        ValueError: if institution_name (after normalizing) or last4 is empty.
    """
    institution = re.sub(r"\s+", "_", institution_name.strip().lower())
    institution = re.sub(r"[^a-z0-9_]", "", institution)
    if not institution:
        raise ValueError("institution_name is required to build a bank account id")
    if not last4:
        raise ValueError("last4 is required to build a bank account id")
    return f"{institution}:{account_type.value}:{last4}"


@dataclass
class BankAccount:
    """A real-world bank account, from any source (Plaid, statement, receipt).

    Will replace Account once journals, statements, and receipts move onto it —
    see docs/PLAID_INTEGRATION_DECISIONS.md #4.
    """

    id: str  # <institution>:<account_type>:<last4> — see PLAID_INTEGRATION_DECISIONS.md #3
    institution_name: str
    account_type: BankAccountType
    last4: str
    display_name: str | None = None
    plaid_institution_id: str | None = None
    plaid_item_id: str | None = None
    plaid_account_id: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["account_type"] = self.account_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "BankAccount":
        return cls(
            id=d["id"],
            institution_name=d["institution_name"],
            account_type=BankAccountType(d["account_type"]),
            last4=d["last4"],
            display_name=d.get("display_name"),
            plaid_institution_id=d.get("plaid_institution_id"),
            plaid_item_id=d.get("plaid_item_id"),
            plaid_account_id=d.get("plaid_account_id"),
        )
