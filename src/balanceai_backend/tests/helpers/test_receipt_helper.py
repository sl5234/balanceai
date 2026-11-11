import datetime
from decimal import Decimal

from balanceai_backend.helpers.receipt_helper import _ACCOUNT_MATCH_TEXT, receipt_consent_message
from balanceai_backend.models.bank_account import PLACEHOLDER_LAST4, BankAccount, BankAccountType
from balanceai_backend.models.journal import Journal
from balanceai_backend.models.receipt import (
    AccountMatch,
    PaymentMethod,
    ReceiptExtraction,
    ReceiptKind,
)

_RECEIPT = ReceiptExtraction(
    date=datetime.date(2026, 11, 8),
    counterparty="Blue Bottle Coffee",
    kind=ReceiptKind.PURCHASE,
    total=Decimal("12.50"),
    tax=Decimal("1.02"),
    payment_method=PaymentMethod.CARD,
    card_last4="1234",
)
_CHECKING = BankAccount(
    id="test_bank:checking:0000",
    institution_name="Test Bank",
    account_type=BankAccountType.CHECKING,
    last4="0000",
)
_JOURNAL = Journal(journal_id="j1", name="Personal", lines=[])


def test_shows_the_receipt_account_journal_and_match():
    message = receipt_consent_message(_RECEIPT, _CHECKING, _JOURNAL, AccountMatch.HISTORY)
    assert message == (
        "Book this receipt?\n"
        "2026-11-08 · Blue Bottle Coffee · purchase $12.50 (tax $1.02)\n"
        "Paid from Test Bank checking ••0000, journal Personal (matched from an earlier receipt)"
    )


def test_cash_shows_its_name_not_the_placeholder():
    cash = BankAccount(
        id="cash:cash:j1",
        institution_name="Cash",
        account_type=BankAccountType.CASH,
        last4=PLACEHOLDER_LAST4,
        display_name="Cash on hand (Personal)",
    )
    message = receipt_consent_message(_RECEIPT, cash, _JOURNAL, AccountMatch.CASH)
    assert "Paid from Cash on hand (Personal)" in message
    assert PLACEHOLDER_LAST4 not in message


def test_says_when_it_wont_be_booked():
    message = receipt_consent_message(_RECEIPT, _CHECKING, None, AccountMatch.USER)
    assert "not in a journal yet, so it won't be booked (chosen by you)" in message


def test_every_account_match_has_wording():
    assert set(_ACCOUNT_MATCH_TEXT) == set(AccountMatch)
