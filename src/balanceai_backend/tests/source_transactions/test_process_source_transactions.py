"""Tests for classify_and_book_transactions, with classification and booking mocked."""

import sqlite3
from unittest.mock import patch

import pytest
from balanceai_backend.bank_link.plaid_item_db import save_plaid_item
from balanceai_backend.db.bank_account_db import upsert_bank_account
from balanceai_backend.db.connection import create_schema
from balanceai_backend.db.journal_db import save_journal
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.journal import Journal
from balanceai_backend.models.plaid_item import PlaidItem
from balanceai_backend.source_transactions import process_source_transactions as process_module
from balanceai_backend.source_transactions.process_source_transactions import (
    classify_and_book_transactions,
)

CLASSIFIED = {"classified": 1, "unclassified": 0, "errors": []}
BOOKED = {"booked": 1, "transfers_paired": 0}


@pytest.fixture
def db():
    """Chase (checking, card) and Ally (savings). Personal holds Chase checking
    and Ally savings, My LLC the Chase card, and Travel nothing."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    for item_id in ("chase", "ally"):
        save_plaid_item(PlaidItem(item_id=item_id, access_token=f"access-{item_id}"), conn=conn)
    for account_id, item_id, account_type in (
        ("chase:checking:0000", "chase", BankAccountType.CHECKING),
        ("chase:credit_card:1111", "chase", BankAccountType.CREDIT_CARD),
        ("ally:savings:2222", "ally", BankAccountType.SAVINGS),
    ):
        upsert_bank_account(
            BankAccount(
                id=account_id,
                institution_name=item_id,
                account_type=account_type,
                last4=account_id[-4:],
                plaid_item_id=item_id,
            ),
            conn=conn,
        )
    for journal_id, bank_account_ids in (
        ("personal", ["chase:checking:0000", "ally:savings:2222"]),
        ("llc", ["chase:credit_card:1111"]),
        ("travel", []),
    ):
        save_journal(
            Journal(journal_id=journal_id, name=journal_id, bank_account_ids=bank_account_ids),
            conn,
        )
    yield conn
    conn.close()


@pytest.fixture
def calls():
    """Fake classification and booking, recording the order they run in."""
    log: list[str] = []
    with (
        patch.object(
            process_module,
            "classify_transactions",
            side_effect=lambda item_id, conn: log.append("classify") or CLASSIFIED,
        ),
        patch.object(
            process_module,
            "book_transactions",
            side_effect=lambda journal_id, conn: log.append(journal_id) or BOOKED,
        ),
    ):
        yield log


class TestClassifyAndBookSourceTransactions:
    def test_classifies_then_books(self, db, calls):
        result = classify_and_book_transactions("ally", db)

        assert calls == ["classify", "personal"]
        assert result == {"classification": CLASSIFIED, "booking": {"personal": BOOKED}}

    def test_books_every_journal_holding_the_banks_accounts(self, db, calls):
        result = classify_and_book_transactions("chase", db)

        assert set(result["booking"]) == {"personal", "llc"}

    def test_no_bank_books_every_journal_with_accounts(self, db, calls):
        result = classify_and_book_transactions(conn=db)

        assert set(result["booking"]) == {"personal", "llc"}

    def test_one_journals_error_doesnt_stop_the_others(self, db, calls):
        def book(journal_id, conn):
            if journal_id == "personal":
                raise sqlite3.OperationalError("database is locked")
            return BOOKED

        with patch.object(process_module, "book_transactions", side_effect=book):
            result = classify_and_book_transactions("chase", db)

        assert result["booking"] == {
            "personal": {"error": "database is locked"},
            "llc": BOOKED,
        }
