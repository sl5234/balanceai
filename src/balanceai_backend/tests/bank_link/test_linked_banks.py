import sqlite3
from unittest.mock import patch

import pytest
from balanceai_backend.bank_link.linked_banks import (
    _bank_name_key,
    find_item_with_same_accounts,
    find_linked_bank,
    handle_already_linked_bank,
    resolve_duplicate_link,
    update_link,
)
from balanceai_backend.bank_link.plaid_item_db import save_plaid_item
from balanceai_backend.db.bank_account_db import upsert_bank_account
from balanceai_backend.db.connection import create_schema
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.plaid_item import PlaidItem
from balanceai_backend.services.plaid import PlaidAccount, PlaidItemHealth

_MODULE = "balanceai_backend.bank_link.linked_banks"
_LINKED = PlaidItem(item_id="item-1", access_token="a", institution_name="Tartan Bank")


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    yield conn
    conn.close()


def _link(db, item_id, institution_name):
    save_plaid_item(
        PlaidItem(item_id=item_id, access_token=f"a-{item_id}", institution_name=institution_name),
        conn=db,
    )


class TestFindLinkedBank:
    @pytest.mark.parametrize("asked", ["Tartan", "tartan bank", "TARTAN-BANK", "Tartan Bank Inc."])
    def test_matches_ignoring_case_spaces_and_punctuation(self, db, asked):
        _link(db, "item-1", "Tartan Bank")
        assert find_linked_bank(asked, conn=db).item_id == "item-1"

    @pytest.mark.parametrize("asked", ["Platypus", "", "&."])
    def test_no_match(self, db, asked):
        _link(db, "item-1", "Tartan Bank")
        assert find_linked_bank(asked, conn=db) is None

    def test_two_matches_return_none(self, db):
        _link(db, "item-1", "Tartan Bank")
        _link(db, "item-2", "Tartan Bank")
        assert find_linked_bank("tartan", conn=db) is None

    def test_a_bank_with_no_name_never_matches(self, db):
        _link(db, "item-1", None)
        assert find_linked_bank("tartan", conn=db) is None


def test_bank_name_key():
    assert _bank_name_key("Acme Bank & Co.") == "acmebankco"


class TestHandleAlreadyLinkedBank:
    def _handle(self, health, updated=None):
        with (
            patch(f"{_MODULE}.get_plaid_item_health", return_value=health),
            patch(f"{_MODULE}.update_link", return_value=updated) as mock_update,
        ):
            return handle_already_linked_bank(_LINKED), mock_update

    def test_a_working_bank_opens_nothing(self):
        result, mock_update = self._handle(PlaidItemHealth(found=True))
        assert result == {
            "already_linked": True,
            "item_id": "item-1",
            "institution_name": "Tartan Bank",
            "error_code": None,
        }
        mock_update.assert_not_called()

    def test_a_broken_login_is_fixed_in_update_mode(self):
        updated = {"item_id": "item-1", "institution_name": "Tartan Bank", "bank_accounts": {}}
        result, mock_update = self._handle(
            PlaidItemHealth(found=True, error_code="ITEM_LOGIN_REQUIRED"), updated
        )
        assert result == {**updated, "updated": True}
        assert mock_update.call_args.args[0] is _LINKED

    def test_another_error_is_reported_without_opening_anything(self):
        result, mock_update = self._handle(
            PlaidItemHealth(found=True, error_code="INSTITUTION_DOWN")
        )
        assert result["already_linked"] is True and result["error_code"] == "INSTITUTION_DOWN"
        mock_update.assert_not_called()

    def test_gone_at_plaid_links_anew(self):
        result, mock_update = self._handle(PlaidItemHealth(found=False))
        assert result is None
        mock_update.assert_not_called()


class TestUpdateLink:
    @pytest.mark.parametrize("add_accounts", [False, True])
    def test_runs_update_mode_and_refreshes_accounts(self, db, add_accounts):
        accounts = {"saved": ["tartan_bank:checking:0000"], "skipped": []}
        with (
            patch(f"{_MODULE}.run_plaid_link_flow", return_value=_LINKED) as mock_flow,
            patch(f"{_MODULE}.sync_bank_accounts_from_plaid", return_value=accounts),
        ):
            result = update_link(_LINKED, add_accounts=add_accounts, conn=db)
        mock_flow.assert_called_once_with(_LINKED, add_accounts=add_accounts)
        assert result == {
            "item_id": "item-1",
            "institution_name": "Tartan Bank",
            "bank_accounts": accounts,
        }
        assert "access_token" not in str(result)


_NEW = PlaidItem(item_id="item-new", access_token="a-new", institution_name="Tartan Bank")


def _plaid_account(subtype="checking", mask="0000", type_="depository"):
    return PlaidAccount(account_id=f"p-{mask}", name="Acct", type=type_, subtype=subtype, mask=mask)


def _stored_account(db, account_id, plaid_item_id):
    _, account_type, last4 = account_id.split(":")
    upsert_bank_account(
        BankAccount(
            id=account_id,
            institution_name="Tartan Bank",
            account_type=BankAccountType(account_type),
            last4=last4,
            plaid_item_id=plaid_item_id,
            plaid_account_id=f"old-{last4}" if plaid_item_id else None,
        ),
        conn=db,
    )


class TestFindItemWithSameAccounts:
    def _find(self, db, accounts, new_item=_NEW):
        with patch(f"{_MODULE}.get_accounts", return_value=accounts):
            return find_item_with_same_accounts(new_item, conn=db)

    def test_an_account_linked_through_another_item_is_a_duplicate(self, db):
        _link(db, "item-1", "Tartan Bank")
        _stored_account(db, "tartan_bank:checking:0000", "item-1")
        assert self._find(db, [_plaid_account()]).item_id == "item-1"

    def test_a_different_login_at_the_same_bank_isnt(self, db):
        _link(db, "item-1", "Tartan Bank")
        _stored_account(db, "tartan_bank:checking:0000", "item-1")
        assert self._find(db, [_plaid_account(subtype="savings", mask="2222")]) is None

    def test_a_new_bank_isnt(self, db):
        assert self._find(db, [_plaid_account()]) is None

    def test_an_account_with_no_plaid_link_isnt(self, db):
        """E.g. created from statements or receipts: account sync just links it."""
        _stored_account(db, "tartan_bank:checking:0000", None)
        assert self._find(db, [_plaid_account()]) is None

    @pytest.mark.parametrize(
        "account",
        [_plaid_account(type_="other", subtype=None), _plaid_account(mask=None)],
        ids=["unsupported_type", "no_last4"],
    )
    def test_accounts_that_cant_be_stored_are_skipped(self, db, account):
        _link(db, "item-1", "Tartan Bank")
        _stored_account(db, "tartan_bank:checking:0000", "item-1")
        assert self._find(db, [account]) is None

    def test_an_item_with_no_bank_name_is_never_a_duplicate(self, db):
        nameless = PlaidItem(item_id="item-new", access_token="a-new")
        assert self._find(db, [_plaid_account()], new_item=nameless) is None


class TestResolveDuplicateLink:
    def _resolve(self, existing, health=None):
        with (
            patch(f"{_MODULE}.find_item_with_same_accounts", return_value=existing),
            patch(f"{_MODULE}.get_plaid_item_health", return_value=health),
            patch(f"{_MODULE}.remove_plaid_item") as mock_remove,
            patch(f"{_MODULE}.run_plaid_link_flow") as mock_flow,
        ):
            result = resolve_duplicate_link(_NEW)
        mock_flow.assert_not_called()  # never opens Plaid
        return result, mock_remove

    def test_not_a_duplicate_keeps_the_new_item(self):
        result, mock_remove = self._resolve(None)
        assert result is None
        mock_remove.assert_not_called()

    def test_a_duplicate_of_a_working_bank_is_removed(self):
        result, mock_remove = self._resolve(_LINKED, PlaidItemHealth(found=True))
        mock_remove.assert_called_once_with("a-new")
        assert result["duplicate_removed"] is True
        assert result["item_id"] == "item-1"
        assert "login_required" not in result
        assert "already connected" in result["message"]

    def test_a_duplicate_of_a_bank_needing_login_asks_for_it(self):
        result, mock_remove = self._resolve(
            _LINKED, PlaidItemHealth(found=True, error_code="ITEM_LOGIN_REQUIRED")
        )
        mock_remove.assert_called_once_with("a-new")
        assert result["login_required"] is True
        assert "update_bank_link" in result["message"]

    def test_a_duplicate_of_a_bank_with_another_error_reports_it(self):
        result, _ = self._resolve(
            _LINKED, PlaidItemHealth(found=True, error_code="INSTITUTION_DOWN")
        )
        assert result["error_code"] == "INSTITUTION_DOWN"
        assert "login_required" not in result

    def test_a_bank_removed_at_plaid_isnt_supported_yet(self):
        result, mock_remove = self._resolve(_LINKED, PlaidItemHealth(found=False))
        mock_remove.assert_called_once_with("a-new")
        assert "isn't supported yet" in result["message"]

    def test_the_new_item_is_removed_before_checking_the_old_one(self):
        calls = []
        with (
            patch(f"{_MODULE}.find_item_with_same_accounts", return_value=_LINKED),
            patch(f"{_MODULE}.remove_plaid_item", side_effect=lambda _: calls.append("remove")),
            patch(
                f"{_MODULE}.get_plaid_item_health",
                side_effect=lambda _: calls.append("health") or PlaidItemHealth(found=True),
            ),
        ):
            resolve_duplicate_link(_NEW)
        assert calls == ["remove", "health"]
