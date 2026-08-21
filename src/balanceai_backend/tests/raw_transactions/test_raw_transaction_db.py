import datetime
import sqlite3
from decimal import Decimal

import pytest
from balanceai_backend.bank_link.plaid_item_db import delete_plaid_item, save_plaid_item
from balanceai_backend.db.connection import create_schema
from balanceai_backend.models.plaid_item import PlaidItem
from balanceai_backend.models.raw_transaction import RawTransaction
from balanceai_backend.raw_transactions.raw_transaction_db import (
    delete_raw_transaction,
    find_raw_transactions,
    upsert_raw_transaction,
)


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


@pytest.fixture
def sample_txn():
    return RawTransaction(
        id="txn-1",
        source="plaid",
        plaid_item_id="item-1",
        account_id="plaid-acc-1",
        posting_date=datetime.date(2026, 8, 19),
        description="Starbucks",
        amount=Decimal("-4.50"),
        category="FOOD_AND_DRINK",
        pending=False,
    )


class TestFindRawTransactions:
    def test_returns_empty_list_when_none_saved(self, db, linked_item):
        assert find_raw_transactions(conn=db) == []

    def test_returns_saved_transaction(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)
        [txn] = find_raw_transactions(conn=db)
        assert txn.id == "txn-1"
        assert txn.description == "Starbucks"
        assert txn.amount == Decimal("-4.50")

    def test_filters_by_plaid_item_id(self, db):
        save_plaid_item(PlaidItem(item_id="item-1", access_token="a"), conn=db)
        save_plaid_item(PlaidItem(item_id="item-2", access_token="b"), conn=db)
        upsert_raw_transaction(
            RawTransaction(
                id="txn-1",
                source="plaid",
                plaid_item_id="item-1",
                account_id="acc-1",
                posting_date=datetime.date(2026, 8, 19),
                description="A",
                amount=Decimal(1),
            ),
            conn=db,
        )
        upsert_raw_transaction(
            RawTransaction(
                id="txn-2",
                source="plaid",
                plaid_item_id="item-2",
                account_id="acc-2",
                posting_date=datetime.date(2026, 8, 19),
                description="B",
                amount=Decimal(2),
            ),
            conn=db,
        )
        [txn] = find_raw_transactions(plaid_item_id="item-2", conn=db)
        assert txn.id == "txn-2"

    def test_filters_by_account_id(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)
        assert len(find_raw_transactions(account_id="plaid-acc-1", conn=db)) == 1
        assert find_raw_transactions(account_id="plaid-acc-nonexistent", conn=db) == []

    def test_filters_by_source(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)
        upsert_raw_transaction(
            RawTransaction(
                id="txn-receipt-1",
                source="receipt",
                plaid_item_id=None,
                account_id="acct-1",
                posting_date=datetime.date(2026, 8, 19),
                description="Grocery receipt",
                amount=Decimal("-30.00"),
            ),
            conn=db,
        )
        [txn] = find_raw_transactions(source="receipt", conn=db)
        assert txn.id == "txn-receipt-1"
        assert txn.plaid_item_id is None


class TestUpsertRawTransaction:
    def test_replaces_existing_transaction_on_same_id(self, db, linked_item, sample_txn):
        """Simulates Plaid's `modified` bucket: same transaction_id, changed fields —
        e.g. a pending charge posting with a finalized amount."""
        upsert_raw_transaction(sample_txn, conn=db)

        modified = RawTransaction(
            id="txn-1",
            source="plaid",
            plaid_item_id="item-1",
            account_id="plaid-acc-1",
            posting_date=datetime.date(2026, 8, 19),
            description="Starbucks",
            amount=Decimal("-4.75"),
            pending=False,
        )
        upsert_raw_transaction(modified, conn=db)

        transactions = find_raw_transactions(conn=db)
        assert len(transactions) == 1
        assert transactions[0].amount == Decimal("-4.75")

    def test_non_plaid_source_allows_null_plaid_item_id(self, db):
        """Confirms plaid_item_id is genuinely nullable — a receipt/bank-statement
        row shouldn't need a fake Plaid item just to satisfy the schema."""
        txn = RawTransaction(
            id="txn-statement-1",
            source="bank_statement",
            plaid_item_id=None,
            account_id="acct-1",
            posting_date=datetime.date(2026, 8, 19),
            description="Check deposit",
            amount=Decimal("500.00"),
        )
        upsert_raw_transaction(txn, conn=db)
        [saved] = find_raw_transactions(conn=db)
        assert saved.plaid_item_id is None
        assert saved.source == "bank_statement"


class TestDeleteRawTransaction:
    def test_removes_transaction(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)
        delete_raw_transaction("txn-1", conn=db)
        assert find_raw_transactions(conn=db) == []

    def test_silently_no_ops_when_not_found(self, db, linked_item):
        delete_raw_transaction("txn-missing", conn=db)  # should not raise


class TestCascadeDelete:
    def test_deleting_item_also_deletes_its_transactions(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)
        delete_plaid_item("item-1", conn=db)
        assert find_raw_transactions(conn=db) == []
