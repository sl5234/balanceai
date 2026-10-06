"""Tests for helpers/plaid_helper.py — creating BankAccounts from Plaid's
/accounts/get, and saving a newly linked item. The Plaid call itself
(services.plaid.get_accounts) is patched to return PlaidAccounts directly.
"""

import sqlite3
from unittest.mock import patch

import pytest
from balanceai_backend.bank_link.plaid_item_db import find_plaid_items, save_plaid_item
from balanceai_backend.db.bank_account_db import find_bank_accounts
from balanceai_backend.db.connection import create_schema
from balanceai_backend.helpers.plaid_helper import (
    bank_account_type_from_plaid,
    save_linked_plaid_item,
    sync_bank_accounts_from_plaid,
)
from balanceai_backend.models.bank_account import BankAccountType
from balanceai_backend.models.plaid_item import PlaidItem
from balanceai_backend.services.plaid import PlaidAccount


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def item(db):
    item = PlaidItem(
        item_id="item-1",
        access_token="access-sandbox-abc",
        institution_id="ins_109511",
        institution_name="Tartan Bank",
    )
    save_plaid_item(item, conn=db)
    return item


def _plaid_account(account_id, plaid_type, subtype, mask, name="Plaid Account"):
    return PlaidAccount(
        account_id=account_id, name=name, type=plaid_type, subtype=subtype, mask=mask
    )


def _sync(item, db, accounts):
    with patch(
        "balanceai_backend.helpers.plaid_helper.get_accounts", return_value=accounts
    ) as mock_get_accounts:
        result = sync_bank_accounts_from_plaid(item, conn=db)
    return result, mock_get_accounts


class TestBankAccountTypeFromPlaid:
    @pytest.mark.parametrize(
        ("plaid_type", "plaid_subtype", "expected"),
        [
            ("depository", "checking", BankAccountType.CHECKING),
            ("depository", "money market", BankAccountType.MONEY_MARKET),
            ("depository", "cd", BankAccountType.CD),
            ("depository", "prepaid", BankAccountType.OTHER_DEPOSITORY),
            ("depository", None, BankAccountType.OTHER_DEPOSITORY),
            ("credit", "credit card", BankAccountType.CREDIT_CARD),
            ("credit", "paypal", BankAccountType.OTHER_CREDIT),
            ("loan", "student", BankAccountType.STUDENT_LOAN),
            ("loan", "consumer", BankAccountType.PERSONAL_LOAN),
            ("loan", "home equity loan", BankAccountType.HOME_EQUITY),
            ("loan", "overdraft", BankAccountType.OTHER_LOAN),
            ("investment", "401k", BankAccountType.RETIREMENT_401K),
            ("investment", "sep ira", BankAccountType.OTHER_INVESTMENT),
            ("brokerage", "brokerage", BankAccountType.BROKERAGE),
        ],
    )
    def test_maps_plaid_type_and_subtype(self, plaid_type, plaid_subtype, expected):
        assert bank_account_type_from_plaid(plaid_type, plaid_subtype) == expected

    def test_returns_none_for_unsupported_type(self):
        assert bank_account_type_from_plaid("other", "other") is None


class TestSyncBankAccountsFromPlaid:
    def test_creates_bank_account_per_plaid_account(self, db, item):
        result, mock_get_accounts = _sync(
            item,
            db,
            [
                _plaid_account("plaid-acc-1", "depository", "checking", "0000", "Plaid Checking"),
                _plaid_account("plaid-acc-2", "credit", "credit card", "3333", "Plaid Credit Card"),
            ],
        )

        assert result == {
            "saved": ["tartan_bank:checking:0000", "tartan_bank:credit_card:3333"],
            "skipped": [],
        }
        mock_get_accounts.assert_called_once_with("access-sandbox-abc")

        [checking] = find_bank_accounts(plaid_account_id="plaid-acc-1", conn=db)
        assert checking.id == "tartan_bank:checking:0000"
        assert checking.institution_name == "Tartan Bank"
        assert checking.display_name == "Plaid Checking"
        assert checking.plaid_institution_id == "ins_109511"
        assert checking.plaid_item_id == "item-1"

    def test_running_again_updates_instead_of_duplicating(self, db, item):
        accounts = [_plaid_account("plaid-acc-1", "depository", "checking", "0000")]
        _sync(item, db, accounts)
        _sync(item, db, accounts)

        assert len(find_bank_accounts(conn=db)) == 1

    def test_skips_unsupported_type_and_missing_mask(self, db, item):
        result, _ = _sync(
            item,
            db,
            [
                _plaid_account("plaid-acc-1", "other", "other", "0000"),
                _plaid_account("plaid-acc-2", "depository", "checking", None),
                _plaid_account("plaid-acc-3", "depository", "savings", "1111"),
            ],
        )

        assert result["saved"] == ["tartan_bank:savings:1111"]
        assert [s["plaid_account_id"] for s in result["skipped"]] == ["plaid-acc-1", "plaid-acc-2"]
        assert "unsupported" in result["skipped"][0]["reason"]
        assert "mask" in result["skipped"][1]["reason"]
        assert result["skipped"][0]["display_name"] == "Plaid Account"

    def test_skips_account_whose_id_is_taken_by_another_plaid_account(self, db, item):
        result, _ = _sync(
            item,
            db,
            [
                _plaid_account("plaid-acc-1", "depository", "checking", "0000"),
                _plaid_account("plaid-acc-2", "depository", "checking", "0000"),
            ],
        )

        assert result["saved"] == ["tartan_bank:checking:0000"]
        assert result["skipped"][0]["plaid_account_id"] == "plaid-acc-2"
        [account] = find_bank_accounts(conn=db)
        assert account.plaid_account_id == "plaid-acc-1"

    def test_raises_when_item_has_no_institution_name(self, db):
        item = PlaidItem(item_id="item-2", access_token="access-sandbox-xyz")

        with pytest.raises(ValueError, match="institution_name"):
            sync_bank_accounts_from_plaid(item, conn=db)


class TestSaveLinkedPlaidItem:
    def test_saves_item_then_creates_bank_accounts(self, db):
        item = PlaidItem(item_id="item-1", access_token="a", institution_name="Tartan Bank")
        saved_before_accounts = []

        def fake_sync(synced_item, conn):
            saved_before_accounts.append(bool(find_plaid_items(item_id="item-1", conn=conn)))
            return {"saved": ["tartan_bank:checking:0000"], "skipped": []}

        with patch(
            "balanceai_backend.helpers.plaid_helper.sync_bank_accounts_from_plaid",
            side_effect=fake_sync,
        ) as mock_sync:
            result = save_linked_plaid_item(item, conn=db)

        assert saved_before_accounts == [True]
        mock_sync.assert_called_once_with(item, conn=db)
        assert result == {"saved": ["tartan_bank:checking:0000"], "skipped": []}

    def test_keeps_item_when_bank_account_creation_fails(self, db):
        item = PlaidItem(item_id="item-1", access_token="a")

        with (
            patch(
                "balanceai_backend.helpers.plaid_helper.sync_bank_accounts_from_plaid",
                side_effect=ValueError("Plaid item item-1 has no institution_name"),
            ),
            pytest.raises(ValueError),
        ):
            save_linked_plaid_item(item, conn=db)

        assert [i.item_id for i in find_plaid_items(conn=db)] == ["item-1"]
