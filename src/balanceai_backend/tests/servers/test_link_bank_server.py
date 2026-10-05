import asyncio
import datetime
import webbrowser
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from balanceai_backend.bank_link.link import LinkExitedError
from balanceai_backend.models.plaid_item import PlaidItem
from balanceai_backend.models.raw_transaction import RawTransaction
from balanceai_backend.servers.link_bank_server import (
    ShareTransactionsConsent,
    get_bank_transactions,
    link_bank,
    list_linked_banks,
    sync_bank_transactions,
)
from mcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)


class TestLinkBank:
    def test_opens_browser_and_returns_linked_item_summary(self):
        item = PlaidItem(
            item_id="item-1",
            access_token="access-sandbox-should-never-appear",
            institution_name="Tartan Bank",
            plaid_account_ids=["acc-1", "acc-2"],
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
                "balanceai_backend.servers.link_bank_server.create_hosted_link",
                return_value=("link-token-1", "https://plaid.com/hosted/abc"),
            ),
            patch(
                "balanceai_backend.servers.link_bank_server.complete_link", return_value=item
            ) as mock_complete,
            patch(
                "balanceai_backend.servers.link_bank_server.save_linked_plaid_item",
                return_value=bank_accounts,
            ) as mock_save,
            patch("balanceai_backend.servers.link_bank_server.webbrowser.open") as mock_open,
        ):
            result = link_bank()

        mock_open.assert_called_once_with("https://plaid.com/hosted/abc")
        mock_complete.assert_called_once_with("link-token-1")
        mock_save.assert_called_once_with(item)
        assert result == {
            "item_id": "item-1",
            "institution_name": "Tartan Bank",
            "bank_accounts": bank_accounts,
        }
        assert "access_token" not in result
        assert "access-sandbox-should-never-appear" not in str(result)

    def test_completes_link_even_when_browser_cannot_open(self):
        item = PlaidItem(item_id="item-1", access_token="a", plaid_account_ids=[])
        with (
            patch(
                "balanceai_backend.servers.link_bank_server.create_hosted_link",
                return_value=("link-token-1", "https://plaid.com/hosted/abc"),
            ),
            patch("balanceai_backend.servers.link_bank_server.complete_link", return_value=item),
            patch("balanceai_backend.servers.link_bank_server.save_linked_plaid_item"),
            patch(
                "balanceai_backend.servers.link_bank_server.webbrowser.open",
                side_effect=webbrowser.Error("no browser available"),
            ),
        ):
            result = link_bank()

        assert result["item_id"] == "item-1"

    def test_propagates_link_exited_error(self):
        with (
            patch(
                "balanceai_backend.servers.link_bank_server.create_hosted_link",
                return_value=("link-token-1", "https://plaid.com/hosted/abc"),
            ),
            patch(
                "balanceai_backend.servers.link_bank_server.complete_link",
                side_effect=LinkExitedError("user exited Hosted Link"),
            ),
            patch("balanceai_backend.servers.link_bank_server.webbrowser.open"),
            pytest.raises(LinkExitedError),
        ):
            link_bank()

    def test_propagates_timeout_error(self):
        with (
            patch(
                "balanceai_backend.servers.link_bank_server.create_hosted_link",
                return_value=("link-token-1", "https://plaid.com/hosted/abc"),
            ),
            patch(
                "balanceai_backend.servers.link_bank_server.complete_link",
                side_effect=TimeoutError("timed out"),
            ),
            patch("balanceai_backend.servers.link_bank_server.webbrowser.open"),
            pytest.raises(TimeoutError),
        ):
            link_bank()


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


class TestSyncBankTransactions:
    def test_delegates_to_sync_transactions_by_item_id(self):
        with patch(
            "balanceai_backend.servers.link_bank_server.db_sync_transactions",
            return_value={"added": 3, "modified": 1, "removed": 0},
        ) as mock_sync:
            result = sync_bank_transactions("item-1")

        mock_sync.assert_called_once_with("item-1")
        assert result == {"added": 3, "modified": 1, "removed": 0}

    def test_defaults_to_the_only_linked_item_when_item_id_omitted(self):
        item = PlaidItem(item_id="item-1", access_token="access-sandbox-abc")
        with (
            patch(
                "balanceai_backend.servers.link_bank_server.db_find_plaid_items",
                return_value=[item],
            ),
            patch(
                "balanceai_backend.servers.link_bank_server.db_sync_transactions",
                return_value={"added": 0, "modified": 0, "removed": 0},
            ) as mock_sync,
        ):
            sync_bank_transactions()

        mock_sync.assert_called_once_with("item-1")

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


def _make_txn(txn_id: str, posting_date: datetime.date) -> RawTransaction:
    return RawTransaction(
        id=txn_id,
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
            "balanceai_backend.servers.link_bank_server.db_find_raw_transactions",
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
                "balanceai_backend.servers.link_bank_server.db_find_raw_transactions",
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
                "balanceai_backend.servers.link_bank_server.db_find_raw_transactions",
                return_value=[_make_txn("txn-1", datetime.date(2026, 8, 19))],
            ),
            pytest.raises(RuntimeError),
        ):
            asyncio.run(get_bank_transactions(ctx))

    def test_returns_empty_list_without_asking_when_no_transactions_synced(self):
        ctx = _make_ctx(DeclinedElicitation())
        with patch(
            "balanceai_backend.servers.link_bank_server.db_find_raw_transactions",
            return_value=[],
        ):
            assert asyncio.run(get_bank_transactions(ctx)) == []

        ctx.elicit.assert_not_called()
