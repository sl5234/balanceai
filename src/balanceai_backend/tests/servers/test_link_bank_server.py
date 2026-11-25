import asyncio
import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import plaid
import pytest
from balanceai_backend.bank_link.link import LinkExitedError
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.consent import ShareTransactionsConsent
from balanceai_backend.models.plaid_item import PlaidItem
from balanceai_backend.models.source_transaction import SourceTransaction
from balanceai_backend.servers.link_bank_server import (
    get_bank_transactions,
    link_bank,
    list_bank_accounts,
    list_linked_banks,
    sync_bank_transactions,
    update_bank_link,
)
from mcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)

_SERVER = "balanceai_backend.servers.link_bank_server"


@pytest.fixture(autouse=True)
def no_duplicate_link():
    """link_bank's check after Link calls Plaid; by default it finds no
    duplicate. Tests that need one patch it themselves."""
    with patch(f"{_SERVER}.resolve_duplicate_link", return_value=None) as mock:
        yield mock


class TestLinkBank:
    def test_runs_the_link_flow_and_returns_linked_item_summary(self):
        item = PlaidItem(
            item_id="item-1",
            access_token="access-sandbox-should-never-appear",
            institution_name="Tartan Bank",
        )
        bank_accounts = {
            "saved": ["tartan_bank:checking:0000"],
            "skipped": [
                {
                    "plaid_account_id": "acc-2",
                    "display_name": "Plaid Other",
                    "reason": "unsupported Plaid account type 'other'",
                }
            ],
        }
        with (
            patch(
                f"{_SERVER}.run_plaid_link_flow", new_callable=AsyncMock, return_value=item
            ) as mock_flow,
            patch(f"{_SERVER}.save_linked_plaid_item", return_value=bank_accounts) as mock_save,
        ):
            result = asyncio.run(link_bank())

        mock_flow.assert_called_once_with()
        mock_save.assert_called_once_with(item)
        assert result == {
            "item_id": "item-1",
            "institution_name": "Tartan Bank",
            "bank_accounts": bank_accounts,
        }
        assert "access-sandbox-should-never-appear" not in str(result)

    @pytest.mark.parametrize("error", [LinkExitedError("exited"), TimeoutError("timed out")])
    def test_propagates_link_errors_and_saves_nothing(self, error):
        with (
            patch(f"{_SERVER}.run_plaid_link_flow", new_callable=AsyncMock, side_effect=error),
            patch(f"{_SERVER}.save_linked_plaid_item") as mock_save,
            pytest.raises(type(error)),
        ):
            asyncio.run(link_bank())
        mock_save.assert_not_called()


class TestUpdateBankLink:
    def test_raises_when_the_bank_isnt_linked(self):
        with (
            patch(f"{_SERVER}.db_find_plaid_items", return_value=[]),
            patch(f"{_SERVER}.update_link", new_callable=AsyncMock) as mock_update,
            pytest.raises(ValueError, match="isn't linked"),
        ):
            asyncio.run(update_bank_link("item-missing"))
        mock_update.assert_not_called()

    @pytest.mark.parametrize("add_accounts", [False, True])
    def test_updates_the_stored_item(self, add_accounts):
        item = PlaidItem(item_id="item-1", access_token="a", institution_name="Tartan Bank")
        updated = {"item_id": "item-1", "institution_name": "Tartan Bank", "bank_accounts": {}}
        with (
            patch(f"{_SERVER}.db_find_plaid_items", return_value=[item]),
            patch(
                f"{_SERVER}.update_link", new_callable=AsyncMock, return_value=updated
            ) as mock_update,
        ):
            assert asyncio.run(update_bank_link("item-1", add_accounts=add_accounts)) == updated
        mock_update.assert_called_once_with(item, add_accounts=add_accounts)


class TestLinkBankWithBankName:
    def test_an_already_linked_bank_returns_its_handling(self):
        linked = PlaidItem(item_id="item-1", access_token="a", institution_name="Tartan Bank")
        response = {"already_linked": True, "item_id": "item-1"}
        with (
            patch(f"{_SERVER}.find_linked_bank", return_value=linked) as mock_find,
            patch(
                f"{_SERVER}.handle_already_linked_bank",
                new_callable=AsyncMock,
                return_value=response,
            ),
            patch(f"{_SERVER}.run_plaid_link_flow", new_callable=AsyncMock) as mock_flow,
        ):
            assert asyncio.run(link_bank("tartan")) == response
        mock_find.assert_called_once_with("tartan")
        mock_flow.assert_not_called()

    @pytest.mark.parametrize(
        ("found", "handled"), [(None, None), ("linked", None)], ids=["no_match", "gone_at_plaid"]
    )
    def test_otherwise_links_anew(self, found, handled):
        linked = PlaidItem(item_id="item-1", access_token="a") if found else None
        item = PlaidItem(item_id="item-2", access_token="b", institution_name="Tartan Bank")
        with (
            patch(f"{_SERVER}.find_linked_bank", return_value=linked),
            patch(
                f"{_SERVER}.handle_already_linked_bank",
                new_callable=AsyncMock,
                return_value=handled,
            ),
            patch(f"{_SERVER}.run_plaid_link_flow", new_callable=AsyncMock, return_value=item),
            patch(f"{_SERVER}.save_linked_plaid_item", return_value={"saved": [], "skipped": []}),
        ):
            assert asyncio.run(link_bank("tartan"))["item_id"] == "item-2"

    def test_a_duplicate_link_isnt_saved(self):
        item = PlaidItem(item_id="item-2", access_token="b")
        duplicate = {"duplicate_removed": True, "item_id": "item-1", "message": "..."}
        with (
            patch(f"{_SERVER}.run_plaid_link_flow", new_callable=AsyncMock, return_value=item),
            patch(f"{_SERVER}.resolve_duplicate_link", return_value=duplicate),
            patch(f"{_SERVER}.save_linked_plaid_item") as mock_save,
        ):
            assert asyncio.run(link_bank()) == duplicate
        mock_save.assert_not_called()

    def test_without_a_name_nothing_is_looked_up(self):
        item = PlaidItem(item_id="item-2", access_token="b")
        with (
            patch(f"{_SERVER}.find_linked_bank") as mock_find,
            patch(f"{_SERVER}.run_plaid_link_flow", new_callable=AsyncMock, return_value=item),
            patch(f"{_SERVER}.save_linked_plaid_item", return_value={"saved": [], "skipped": []}),
        ):
            asyncio.run(link_bank())
        mock_find.assert_not_called()


class TestListLinkedBanks:
    def test_returns_empty_list_when_no_banks_linked(self):
        with patch(
            "balanceai_backend.servers.link_bank_server.db_find_plaid_items", return_value=[]
        ):
            assert list_linked_banks() == []

    def test_omits_access_token_from_result(self):
        item = PlaidItem(
            item_id="item-1",
            access_token="access-sandbox-should-never-appear",
            institution_id="ins_1",
            institution_name="Tartan Bank",
        )
        with patch(
            "balanceai_backend.servers.link_bank_server.db_find_plaid_items",
            return_value=[item],
        ):
            result = list_linked_banks()

        assert result == [
            {
                "item_id": "item-1",
                "institution_id": "ins_1",
                "institution_name": "Tartan Bank",
            }
        ]
        assert "access_token" not in result[0]
        assert "access-sandbox-should-never-appear" not in str(result)


class TestListBankAccounts:
    def test_returns_accounts_as_dicts(self):
        account = BankAccount(
            id="tartan_bank:checking:0000",
            institution_name="Tartan Bank",
            account_type=BankAccountType.CHECKING,
            last4="0000",
            plaid_item_id="item-1",
            plaid_account_id="plaid-acc-1",
        )
        with patch(
            "balanceai_backend.servers.link_bank_server.db_find_bank_accounts",
            return_value=[account],
        ) as mock_find:
            result = list_bank_accounts()

        mock_find.assert_called_once_with(plaid_item_id=None)
        assert result == [account.to_dict()]
        assert result[0]["account_type"] == "checking"

    def test_filters_by_item_id(self):
        with patch(
            "balanceai_backend.servers.link_bank_server.db_find_bank_accounts", return_value=[]
        ) as mock_find:
            assert list_bank_accounts(item_id="item-1") == []

        mock_find.assert_called_once_with(plaid_item_id="item-1")


_CLASSIFIED_AND_BOOKED = {
    "classification": {"classified": 2, "unclassified": 0, "errors": []},
    "booking": {"journal-1": {"booked": 2, "transfers_paired": 0}},
}


class TestSyncBankTransactions:
    @pytest.fixture(autouse=True)
    def fake_classifier(self):
        """Never run the real classifier and booking here: they would use the
        real database and call the AI."""
        with patch(
            "balanceai_backend.servers.link_bank_server.classify_and_book_transactions",
            return_value=_CLASSIFIED_AND_BOOKED,
        ) as mock:
            yield mock

    def test_a_login_needed_error_says_to_log_in_again(self, fake_classifier):
        error = plaid.ApiException(status=400)
        error.body = '{"error_code": "ITEM_LOGIN_REQUIRED", "error_message": "..."}'
        with (
            patch(f"{_SERVER}.sync_source_transactions_from_plaid", side_effect=error),
            pytest.raises(ValueError, match="log in again"),
        ):
            sync_bank_transactions("item-1")
        fake_classifier.assert_not_called()

    def test_other_plaid_errors_are_raised_as_is(self):
        error = plaid.ApiException(status=500)
        error.body = '{"error_code": "INTERNAL_SERVER_ERROR"}'
        with (
            patch(f"{_SERVER}.sync_source_transactions_from_plaid", side_effect=error),
            pytest.raises(plaid.ApiException),
        ):
            sync_bank_transactions("item-1")

    def test_delegates_to_sync_transactions_by_item_id(self):
        with patch(
            "balanceai_backend.servers.link_bank_server.sync_source_transactions_from_plaid",
            return_value={"added": 3, "modified": 1, "removed": 0},
        ) as mock_sync:
            result = sync_bank_transactions("item-1")

        mock_sync.assert_called_once_with("item-1")
        assert result == {
            "added": 3,
            "modified": 1,
            "removed": 0,
            **_CLASSIFIED_AND_BOOKED,
        }

    def test_classifies_and_books_the_synced_bank_after_pulling_from_plaid(self, fake_classifier):
        calls = []
        fake_classifier.side_effect = (
            lambda item_id: calls.append("classify") or _CLASSIFIED_AND_BOOKED
        )
        with patch(
            "balanceai_backend.servers.link_bank_server.sync_source_transactions_from_plaid",
            side_effect=lambda item_id: calls.append("pull") or {"added": 1},
        ):
            sync_bank_transactions("item-1")

        assert calls == ["pull", "classify"]
        fake_classifier.assert_called_once_with("item-1")

    def test_does_not_classify_when_the_pull_fails(self, fake_classifier):
        with (
            patch(
                "balanceai_backend.servers.link_bank_server.sync_source_transactions_from_plaid",
                side_effect=ValueError("No bank account for Plaid account"),
            ),
            pytest.raises(ValueError),
        ):
            sync_bank_transactions("item-1")

        fake_classifier.assert_not_called()

    def test_defaults_to_the_only_linked_item_when_item_id_omitted(self, fake_classifier):
        item = PlaidItem(item_id="item-1", access_token="access-sandbox-abc")
        with (
            patch(
                "balanceai_backend.servers.link_bank_server.db_find_plaid_items",
                return_value=[item],
            ),
            patch(
                "balanceai_backend.servers.link_bank_server.sync_source_transactions_from_plaid",
                return_value={"added": 0, "modified": 0, "removed": 0},
            ) as mock_sync,
        ):
            sync_bank_transactions()

        mock_sync.assert_called_once_with("item-1")
        fake_classifier.assert_called_once_with("item-1")

    def test_raises_when_no_banks_linked_and_item_id_omitted(self):
        with (
            patch(
                "balanceai_backend.servers.link_bank_server.db_find_plaid_items",
                return_value=[],
            ),
            pytest.raises(ValueError, match="No banks are linked"),
        ):
            sync_bank_transactions()

    def test_raises_when_multiple_banks_linked_and_item_id_omitted(self):
        items = [
            PlaidItem(item_id="item-1", access_token="a"),
            PlaidItem(item_id="item-2", access_token="b"),
        ]
        with (
            patch(
                "balanceai_backend.servers.link_bank_server.db_find_plaid_items",
                return_value=items,
            ),
            pytest.raises(ValueError, match="Multiple banks are linked"),
        ):
            sync_bank_transactions()


def _make_ctx(elicit_result) -> MagicMock:
    ctx = MagicMock()
    ctx.elicit = AsyncMock(return_value=elicit_result)
    return ctx


def _make_txn(txn_id: str, posting_date: datetime.date) -> SourceTransaction:
    return SourceTransaction(
        source_transaction_id=txn_id,
        source="plaid",
        plaid_item_id="item-1",
        account_id="plaid-acc-1",
        posting_date=posting_date,
        description="Starbucks",
        amount=Decimal("-4.50"),
        category="FOOD_AND_DRINK",
    )


class TestGetBankTransactions:
    def test_returns_transactions_when_user_approves(self):
        txns = [
            _make_txn("txn-1", datetime.date(2026, 8, 19)),
            _make_txn("txn-2", datetime.date(2026, 7, 2)),
        ]
        ctx = _make_ctx(AcceptedElicitation(data=ShareTransactionsConsent()))
        with patch(
            "balanceai_backend.servers.link_bank_server.db_find_source_transactions",
            return_value=txns,
        ) as mock_find:
            result = asyncio.run(
                get_bank_transactions(ctx, item_id="item-1", account_id="plaid-acc-1")
            )

        mock_find.assert_called_once_with(
            plaid_item_id="item-1", account_id="plaid-acc-1", source="plaid"
        )
        ctx.elicit.assert_awaited_once()
        message = ctx.elicit.await_args.kwargs["message"]
        assert "2 bank transactions" in message
        assert "2026-07-02 to 2026-08-19" in message
        assert result == [t.to_dict() for t in txns]

    @pytest.mark.parametrize(
        "elicit_result",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
        ],
        ids=["declined", "cancelled"],
    )
    def test_raises_and_returns_nothing_when_user_does_not_approve(self, elicit_result):
        ctx = _make_ctx(elicit_result)
        with (
            patch(
                "balanceai_backend.servers.link_bank_server.db_find_source_transactions",
                return_value=[_make_txn("txn-1", datetime.date(2026, 8, 19))],
            ),
            pytest.raises(PermissionError, match="declined"),
        ):
            asyncio.run(get_bank_transactions(ctx))

    def test_propagates_error_when_client_does_not_support_elicitation(self):
        ctx = MagicMock()
        ctx.elicit = AsyncMock(side_effect=RuntimeError("elicitation not supported"))
        with (
            patch(
                "balanceai_backend.servers.link_bank_server.db_find_source_transactions",
                return_value=[_make_txn("txn-1", datetime.date(2026, 8, 19))],
            ),
            pytest.raises(RuntimeError),
        ):
            asyncio.run(get_bank_transactions(ctx))

    def test_returns_empty_list_without_asking_when_no_transactions_synced(self):
        ctx = _make_ctx(DeclinedElicitation())
        with patch(
            "balanceai_backend.servers.link_bank_server.db_find_source_transactions",
            return_value=[],
        ):
            assert asyncio.run(get_bank_transactions(ctx)) == []

        ctx.elicit.assert_not_called()
