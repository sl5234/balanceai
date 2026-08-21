import sqlite3

import pytest
from balanceai_backend.bank_link.plaid_item_db import (
    delete_plaid_item,
    find_plaid_items,
    save_plaid_item,
)
from balanceai_backend.db.connection import create_schema
from balanceai_backend.models.plaid_item import PlaidItem


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_item():
    return PlaidItem(
        item_id="item-1",
        access_token="access-sandbox-abc",
        institution_id="ins_3",
        institution_name="Chase",
        plaid_account_ids=["plaid-acc-1", "plaid-acc-2"],
        our_account_ids=["acct-1", "acct-2"],
    )


class TestFindPlaidItems:
    def test_returns_empty_list_when_none_saved(self, db):
        assert find_plaid_items(conn=db) == []

    def test_returns_saved_item(self, db, sample_item):
        save_plaid_item(sample_item, conn=db)
        items = find_plaid_items(conn=db)
        assert len(items) == 1
        assert items[0].item_id == "item-1"
        assert items[0].access_token == "access-sandbox-abc"
        assert items[0].institution_name == "Chase"
        assert items[0].plaid_account_ids == ["plaid-acc-1", "plaid-acc-2"]
        assert items[0].our_account_ids == ["acct-1", "acct-2"]

    def test_filters_by_item_id(self, db):
        save_plaid_item(PlaidItem(item_id="item-1", access_token="a"), conn=db)
        save_plaid_item(PlaidItem(item_id="item-2", access_token="b"), conn=db)
        items = find_plaid_items(item_id="item-2", conn=db)
        assert len(items) == 1
        assert items[0].item_id == "item-2"


class TestSavePlaidItem:
    def test_persists_across_reads(self, db, sample_item):
        save_plaid_item(sample_item, conn=db)
        [reloaded] = find_plaid_items(item_id="item-1", conn=db)
        assert reloaded.access_token == sample_item.access_token


class TestDeletePlaidItem:
    def test_removes_item(self, db, sample_item):
        save_plaid_item(sample_item, conn=db)
        delete_plaid_item("item-1", conn=db)
        assert find_plaid_items(conn=db) == []

    def test_raises_when_not_found(self, db):
        with pytest.raises(ValueError, match="item-missing"):
            delete_plaid_item("item-missing", conn=db)
