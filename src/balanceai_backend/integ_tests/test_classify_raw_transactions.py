"""Integration test for classify_raw_transactions against the real AI.

Known transactions, close to but not copies of the prompt's examples, so this
checks the prompt's rules rather than its examples. Only the counter account
is checked; category and counterparty are free text.

All descriptions differ and Plaid's confidence is HIGH, so this is one AI call
and no web search.

Run with:
    pytest integ_tests/test_classify_raw_transactions.py -v

Requires a configured Anthropic API key (via settings).
"""

import datetime
import sqlite3
from decimal import Decimal
from unittest.mock import patch

import pytest

from balanceai_backend.config import settings
from balanceai_backend.dagger.aws import AWSClients
from balanceai_backend.db.bank_account_db import upsert_bank_account
from balanceai_backend.db.connection import create_schema
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.journal import JournalAccount
from balanceai_backend.models.raw_transaction import RawTransaction
from balanceai_backend.raw_transactions import classify_raw_transactions as classify_module
from balanceai_backend.raw_transactions.classify_raw_transactions import classify_raw_transactions
from balanceai_backend.raw_transactions.raw_transaction_db import (
    find_raw_transactions,
    upsert_raw_transaction,
)

CHECKING = "test_bank:checking:0000"
SAVINGS = "test_bank:savings:1111"
CARD = "test_bank:credit_card:4444"

_ACCOUNT_TYPES = {
    CHECKING: BankAccountType.CHECKING,
    SAVINGS: BankAccountType.SAVINGS,
    CARD: BankAccountType.CREDIT_CARD,
}

# (id, description, amount (negative = money out), account, plaid category, expected)
_CASES = [
    (
        "coffee",
        "Starbucks",
        "-4.75",
        CHECKING,
        "FOOD_AND_DRINK",
        JournalAccount.NON_ESSENTIALS_EXPENSE,
    ),
    (
        "groceries",
        "Safeway",
        "-86.20",
        CHECKING,
        "FOOD_AND_DRINK",
        JournalAccount.ESSENTIALS_EXPENSE,
    ),
    (
        "utilities",
        "PG&E",
        "-120.00",
        CHECKING,
        "RENT_AND_UTILITIES",
        JournalAccount.ESSENTIALS_EXPENSE,
    ),
    ("payroll", "GLOBEX INC PAYROLL", "3200.00", CHECKING, "INCOME", JournalAccount.SALARY_INCOME),
    ("interest", "INTEREST PAID", "3.10", SAVINGS, "INCOME", JournalAccount.INTEREST_INCOME),
    (
        "refund",
        "Delta Air Lines",
        "320.00",
        CHECKING,
        "TRAVEL",
        JournalAccount.NON_ESSENTIALS_EXPENSE,
    ),
    (
        "card_payment",
        "CHASE CARD 4444 PAYMENT",
        "-900.00",
        CHECKING,
        "LOAN_PAYMENTS",
        JournalAccount.CREDIT_CARD_PAYABLE,
    ),
    (
        "card_side_payment",
        "PAYMENT THANK YOU",
        "900.00",
        CARD,
        "LOAN_PAYMENTS",
        JournalAccount.CASH,
    ),
    (
        "to_savings",
        "TRANSFER TO SAVINGS",
        "-1000.00",
        CHECKING,
        "TRANSFER_OUT",
        JournalAccount.CASH,
    ),
    ("late_fee", "LATE FEE", "-39.00", CARD, "BANK_FEES", JournalAccount.INTEREST_AND_FEES),
]


@pytest.fixture(scope="module")
def classified() -> dict[str, JournalAccount]:
    """Classify every case with the real AI once; counter account by transaction id."""
    # The API key is KMS-encrypted; the servers set this up on import.
    aws_clients = AWSClients(region_name=settings.aws_region)
    if not aws_clients.is_initialized():
        aws_clients.initialize()
    settings.set_aws_clients(aws_clients)

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    for account_id, account_type in _ACCOUNT_TYPES.items():
        upsert_bank_account(
            BankAccount(
                id=account_id,
                institution_name="Test Bank",
                account_type=account_type,
                last4=account_id[-4:],
            ),
            conn=conn,
        )
    for txn_id, description, amount, account_id, category, _ in _CASES:
        upsert_raw_transaction(
            RawTransaction(
                id=txn_id,
                source="plaid",
                account_id=account_id,
                posting_date=datetime.date(2026, 10, 1),
                description=description,
                amount=Decimal(amount),
                category=category,
                category_confidence="HIGH",
            ),
            conn=conn,
        )

    # Confidence is HIGH, so no search should run; patched in case one does.
    with patch.object(classify_module.tavily_service, "search", return_value=None):
        result = classify_raw_transactions(conn=conn)

    assert result["errors"] == []
    classified = {
        t.id: t.classification.counter_account
        for t in find_raw_transactions(conn=conn)
        if t.classification is not None
    }
    conn.close()
    return classified


@pytest.mark.parametrize(
    "txn_id, description, amount, account_id, category, expected",
    _CASES,
    ids=[case[0] for case in _CASES],
)
def test_counter_account(classified, txn_id, description, amount, account_id, category, expected):
    assert classified.get(txn_id) == expected
