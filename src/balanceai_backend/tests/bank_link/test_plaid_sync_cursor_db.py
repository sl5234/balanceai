import sqlite3

import pytest
from balanceai_backend.bank_link.plaid_item_db import delete_plaid_item, save_plaid_item
from balanceai_backend.bank_link.plaid_sync_cursor_db import (
    get_plaid_sync_cursor,
    update_plaid_sync_cursor,
)
from balanceai_backend.db.connection import create_schema
from balanceai_backend.models.plaid_item import PlaidItem
from balanceai_backend.models.plaid_sync_cursor import PlaidSyncCursor


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


class TestGetPlaidSyncCursor:
    def test_returns_none_before_first_sync(self, db, linked_item):
        assert get_plaid_sync_cursor("item-1", conn=db) is None

    def test_returns_saved_cursor(self, db, linked_item):
        update_plaid_sync_cursor(PlaidSyncCursor(item_id="item-1", cursor="cursor_AAA"), conn=db)
        assert get_plaid_sync_cursor("item-1", conn=db) == "cursor_AAA"


class TestUpdatePlaidSyncCursor:
    def test_overwrites_on_subsequent_syncs(self, db, linked_item):
        update_plaid_sync_cursor(PlaidSyncCursor(item_id="item-1", cursor="cursor_AAA"), conn=db)
        update_plaid_sync_cursor(PlaidSyncCursor(item_id="item-1", cursor="cursor_BBB"), conn=db)
        assert get_plaid_sync_cursor("item-1", conn=db) == "cursor_BBB"

    def test_cursors_for_different_items_are_independent(self, db):
        save_plaid_item(PlaidItem(item_id="item-1", access_token="a"), conn=db)
        save_plaid_item(PlaidItem(item_id="item-2", access_token="b"), conn=db)
        update_plaid_sync_cursor(PlaidSyncCursor(item_id="item-1", cursor="cursor_A"), conn=db)
        update_plaid_sync_cursor(PlaidSyncCursor(item_id="item-2", cursor="cursor_B"), conn=db)
        assert get_plaid_sync_cursor("item-1", conn=db) == "cursor_A"
        assert get_plaid_sync_cursor("item-2", conn=db) == "cursor_B"


class TestCascadeDelete:
    def test_deleting_item_also_deletes_its_cursor(self, db, linked_item):
        update_plaid_sync_cursor(PlaidSyncCursor(item_id="item-1", cursor="cursor_AAA"), conn=db)
        delete_plaid_item("item-1", conn=db)
        assert get_plaid_sync_cursor("item-1", conn=db) is None
