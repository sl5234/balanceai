import sqlite3

import pytest
from balanceai_backend.bank_link.plaid_item_db import delete_plaid_item, save_plaid_item
from balanceai_backend.db.bank_account_db import find_bank_accounts, upsert_bank_account
from balanceai_backend.db.connection import create_schema
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.plaid_item import PlaidItem


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


def _plaid_account(
    id="tartan_bank:checking:0000", plaid_account_id="plaid-acc-1", display_name="Plaid Checking"
):
    return BankAccount(
        id=id,
        institution_name="Tartan Bank",
        account_type=BankAccountType.CHECKING,
        last4=id.rsplit(":", 1)[1],
        display_name=display_name,
        plaid_institution_id="ins_109511",
        plaid_item_id="item-1",
        plaid_account_id=plaid_account_id,
    )


class TestFindBankAccounts:
    def test_returns_empty_list_when_none_saved(self, db):
        assert find_bank_accounts(conn=db) == []

    def test_filters_by_id_item_and_plaid_account(self, db, linked_item):
        upsert_bank_account(_plaid_account(), conn=db)
        upsert_bank_account(
            _plaid_account(id="tartan_bank:checking:1111", plaid_account_id="plaid-acc-2"),
            conn=db,
        )

        assert [a.id for a in find_bank_accounts(conn=db)] == [
            "tartan_bank:checking:0000",
            "tartan_bank:checking:1111",
        ]
        [by_id] = find_bank_accounts(id="tartan_bank:checking:1111", conn=db)
        assert by_id.plaid_account_id == "plaid-acc-2"
        assert len(find_bank_accounts(plaid_item_id="item-1", conn=db)) == 2
        [by_plaid] = find_bank_accounts(plaid_account_id="plaid-acc-1", conn=db)
        assert by_plaid.id == "tartan_bank:checking:0000"


class TestUpsertBankAccount:
    def test_inserts_and_reads_back(self, db, linked_item):
        account = _plaid_account()
        upsert_bank_account(account, conn=db)
        assert find_bank_accounts(conn=db) == [account]

    def test_updates_existing_account(self, db, linked_item):
        upsert_bank_account(_plaid_account(display_name="Old Name"), conn=db)
        upsert_bank_account(_plaid_account(display_name="New Name"), conn=db)

        [account] = find_bank_accounts(conn=db)
        assert account.display_name == "New Name"

    def test_update_with_none_keeps_existing_optional_fields(self, db, linked_item):
        upsert_bank_account(_plaid_account(), conn=db)
        upsert_bank_account(
            BankAccount(
                id="tartan_bank:checking:0000",
                institution_name="Tartan Bank",
                account_type=BankAccountType.CHECKING,
                last4="0000",
            ),
            conn=db,
        )

        [account] = find_bank_accounts(conn=db)
        assert account.display_name == "Plaid Checking"
        assert account.plaid_item_id == "item-1"
        assert account.plaid_account_id == "plaid-acc-1"

    def test_raises_when_id_already_linked_to_different_plaid_account(self, db, linked_item):
        upsert_bank_account(_plaid_account(plaid_account_id="plaid-acc-1"), conn=db)

        with pytest.raises(ValueError, match="plaid-acc-1"):
            upsert_bank_account(_plaid_account(plaid_account_id="plaid-acc-2"), conn=db)

        [account] = find_bank_accounts(conn=db)
        assert account.plaid_account_id == "plaid-acc-1"

    def test_raises_when_plaid_account_already_under_another_id(self, db, linked_item):
        upsert_bank_account(_plaid_account(id="tartan_bank:checking:0000"), conn=db)

        with pytest.raises(sqlite3.IntegrityError):
            upsert_bank_account(_plaid_account(id="tartan_bank:savings:0000"), conn=db)


class TestPlaidItemDeletion:
    def test_deleting_plaid_item_keeps_account_and_clears_link(self, db, linked_item):
        upsert_bank_account(_plaid_account(), conn=db)

        delete_plaid_item("item-1", conn=db)

        [account] = find_bank_accounts(conn=db)
        assert account.plaid_item_id is None
        assert account.plaid_account_id is None

    def test_relinking_after_delete_attaches_new_plaid_account(self, db, linked_item):
        upsert_bank_account(_plaid_account(plaid_account_id="plaid-acc-1"), conn=db)
        delete_plaid_item("item-1", conn=db)
        save_plaid_item(PlaidItem(item_id="item-1", access_token="access-sandbox-new"), conn=db)

        upsert_bank_account(_plaid_account(plaid_account_id="plaid-acc-new"), conn=db)

        [account] = find_bank_accounts(conn=db)
        assert account.plaid_account_id == "plaid-acc-new"
