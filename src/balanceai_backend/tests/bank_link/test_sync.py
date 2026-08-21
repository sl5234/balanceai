"""Tests for the /transactions/sync loop.

Fake Plaid response objects use SimpleNamespace rather than MagicMock — same
reasoning as test_link.py: Plaid's real generated SDK models raise
ApiAttributeError on unset optional fields instead of returning None, and
SimpleNamespace matches that "attribute genuinely absent" behavior.

Every sync_transactions() call below passes conn=db explicitly — its default
argument is bound once at function-definition time, so patching the storage
modules' module-level _default_conn after the fact would silently do nothing
and these tests would otherwise hit the real data/balanceai.db.
"""

import sqlite3
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from balanceai_backend.bank_link.plaid_item_db import save_plaid_item
from balanceai_backend.bank_link.plaid_sync_cursor_db import get_plaid_sync_cursor
from balanceai_backend.bank_link.sync import sync_transactions
from balanceai_backend.db.connection import create_schema
from balanceai_backend.models.plaid_item import PlaidItem
from balanceai_backend.raw_transactions.raw_transaction_db import find_raw_transactions


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def linked_item(db):
    item = PlaidItem(item_id="item-1", access_token="access-sandbox-abc")
    save_plaid_item(item, conn=db)
    return item


def _plaid_txn(
    transaction_id="txn-1",
    account_id="plaid-acc-1",
    amount=4.50,
    name="STARBUCKS #123",
    merchant_name="Starbucks",
    pending=False,
    personal_finance_category=None,
):
    if personal_finance_category is None:
        personal_finance_category = SimpleNamespace(primary="FOOD_AND_DRINK")
    return SimpleNamespace(
        transaction_id=transaction_id,
        account_id=account_id,
        date=date(2026, 8, 19),
        amount=amount,
        name=name,
        merchant_name=merchant_name,
        pending=pending,
        personal_finance_category=personal_finance_category,
    )


class TestSyncTransactions:
    def test_raises_when_item_not_found(self, db):
        with pytest.raises(ValueError, match="item-missing"):
            sync_transactions("item-missing", conn=db)

    def test_first_sync_omits_cursor(self, db, linked_item):
        mock_client = MagicMock()
        mock_client.transactions_sync.return_value = SimpleNamespace(
            added=[], modified=[], removed=[], next_cursor="cursor-A", has_more=False
        )

        with patch("balanceai_backend.bank_link.sync.get_client", return_value=mock_client):
            sync_transactions("item-1", conn=db)

        request = mock_client.transactions_sync.call_args[0][0]
        assert not hasattr(request, "cursor")
        assert request.access_token == "access-sandbox-abc"

    def test_added_transaction_saved_with_flipped_sign(self, db, linked_item):
        mock_client = MagicMock()
        mock_client.transactions_sync.return_value = SimpleNamespace(
            added=[_plaid_txn(amount=4.50)],
            modified=[],
            removed=[],
            next_cursor="cursor-A",
            has_more=False,
        )

        with patch("balanceai_backend.bank_link.sync.get_client", return_value=mock_client):
            counts = sync_transactions("item-1", conn=db)

        assert counts == {"added": 1, "modified": 0, "removed": 0}
        [txn] = find_raw_transactions(conn=db)
        assert txn.id == "txn-1"
        assert txn.amount == Decimal("-4.5")  # Plaid positive (spend) -> our negative (debit)
        assert txn.description == "Starbucks"
        assert txn.category == "FOOD_AND_DRINK"

    def test_income_transaction_flips_to_positive(self, db, linked_item):
        mock_client = MagicMock()
        mock_client.transactions_sync.return_value = SimpleNamespace(
            added=[_plaid_txn(amount=-1000.0, name="PAYROLL", merchant_name=None)],
            modified=[],
            removed=[],
            next_cursor="cursor-A",
            has_more=False,
        )

        with patch("balanceai_backend.bank_link.sync.get_client", return_value=mock_client):
            sync_transactions("item-1", conn=db)

        [txn] = find_raw_transactions(conn=db)
        assert txn.amount == Decimal("1000.0")  # Plaid negative (deposit) -> our positive (credit)
        assert txn.description == "PAYROLL"  # falls back to name when merchant_name is None

    def test_modified_transaction_replaces_existing_row(self, db, linked_item):
        mock_client = MagicMock()
        mock_client.transactions_sync.side_effect = [
            SimpleNamespace(
                added=[_plaid_txn(amount=4.50)],
                modified=[],
                removed=[],
                next_cursor="cursor-A",
                has_more=False,
            ),
        ]
        with patch("balanceai_backend.bank_link.sync.get_client", return_value=mock_client):
            sync_transactions("item-1", conn=db)

        mock_client.transactions_sync.side_effect = [
            SimpleNamespace(
                added=[],
                modified=[_plaid_txn(amount=4.75)],
                removed=[],
                next_cursor="cursor-B",
                has_more=False,
            ),
        ]
        with patch("balanceai_backend.bank_link.sync.get_client", return_value=mock_client):
            counts = sync_transactions("item-1", conn=db)

        assert counts == {"added": 0, "modified": 1, "removed": 0}
        transactions = find_raw_transactions(conn=db)
        assert len(transactions) == 1
        assert transactions[0].amount == Decimal("-4.75")

    def test_removed_transaction_deletes_existing_row(self, db, linked_item):
        mock_client = MagicMock()
        mock_client.transactions_sync.return_value = SimpleNamespace(
            added=[_plaid_txn()], modified=[], removed=[], next_cursor="cursor-A", has_more=False
        )
        with patch("balanceai_backend.bank_link.sync.get_client", return_value=mock_client):
            sync_transactions("item-1", conn=db)

        mock_client.transactions_sync.return_value = SimpleNamespace(
            added=[],
            modified=[],
            removed=[SimpleNamespace(transaction_id="txn-1", account_id="plaid-acc-1")],
            next_cursor="cursor-B",
            has_more=False,
        )
        with patch("balanceai_backend.bank_link.sync.get_client", return_value=mock_client):
            counts = sync_transactions("item-1", conn=db)

        assert counts == {"added": 0, "modified": 0, "removed": 1}
        assert find_raw_transactions(conn=db) == []

    def test_loops_while_has_more_and_persists_cursor_each_page(self, db, linked_item):
        mock_client = MagicMock()
        mock_client.transactions_sync.side_effect = [
            SimpleNamespace(
                added=[_plaid_txn(transaction_id="txn-1")],
                modified=[],
                removed=[],
                next_cursor="cursor-page-1",
                has_more=True,
            ),
            SimpleNamespace(
                added=[_plaid_txn(transaction_id="txn-2")],
                modified=[],
                removed=[],
                next_cursor="cursor-page-2",
                has_more=False,
            ),
        ]

        with patch("balanceai_backend.bank_link.sync.get_client", return_value=mock_client):
            counts = sync_transactions("item-1", conn=db)

        assert counts == {"added": 2, "modified": 0, "removed": 0}
        assert mock_client.transactions_sync.call_count == 2
        second_call_request = mock_client.transactions_sync.call_args_list[1][0][0]
        assert second_call_request.cursor == "cursor-page-1"
        assert get_plaid_sync_cursor("item-1", conn=db) == "cursor-page-2"

    def test_uses_saved_cursor_on_subsequent_sync(self, db, linked_item):
        mock_client = MagicMock()
        mock_client.transactions_sync.return_value = SimpleNamespace(
            added=[], modified=[], removed=[], next_cursor="cursor-A", has_more=False
        )
        with patch("balanceai_backend.bank_link.sync.get_client", return_value=mock_client):
            sync_transactions("item-1", conn=db)

        mock_client.transactions_sync.return_value = SimpleNamespace(
            added=[], modified=[], removed=[], next_cursor="cursor-B", has_more=False
        )
        with patch("balanceai_backend.bank_link.sync.get_client", return_value=mock_client):
            sync_transactions("item-1", conn=db)

        second_call_request = mock_client.transactions_sync.call_args_list[1][0][0]
        assert second_call_request.cursor == "cursor-A"
