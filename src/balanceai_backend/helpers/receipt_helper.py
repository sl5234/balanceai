from balanceai_backend.models import Journal
from balanceai_backend.models.bank_account import BankAccount
from balanceai_backend.models.receipt import AccountMatch, ReceiptExtraction

# How the paying account was found, in the consent prompt's words.
_ACCOUNT_MATCH_TEXT = {
    AccountMatch.CASH: "the journal's cash account",
    AccountMatch.HISTORY: "matched from an earlier receipt",
    AccountMatch.LAST4: "matched the account's last 4",
    AccountMatch.USER: "chosen by you",
}


def receipt_consent_message(
    receipt: ReceiptExtraction,
    account: BankAccount,
    journal: Journal | None,
    match: AccountMatch,
) -> str:
    """The upload_receipt consent prompt, e.g.
    'Book this receipt?
    2026-11-08 · Blue Bottle Coffee · purchase $12.50 (tax $1.02)
    Paid from Chase checking ••0000, journal Personal (matched from an earlier receipt)'"""
    extras = ", ".join(
        f"{name} ${value}" for name, value in (("tax", receipt.tax), ("tip", receipt.tip)) if value
    )
    amount = f"{receipt.kind.value} ${receipt.total}" + (f" ({extras})" if extras else "")
    name = account.display_name or (
        f"{account.institution_name} {account.account_type.value} ••{account.last4}"
    )
    where = f"journal {journal.name}" if journal else "not in a journal yet, so it won't be booked"
    return (
        "Book this receipt?\n"
        f"{receipt.date.isoformat()} · {receipt.counterparty} · {amount}\n"
        f"Paid from {name}, {where} ({_ACCOUNT_MATCH_TEXT[match]})"
    )
