"""Tests for the Plaid Hosted Link handshake.

Fake Plaid response objects use SimpleNamespace rather than MagicMock: Plaid's
real generated SDK models raise ApiAttributeError on unset optional fields
instead of returning None (verified against the installed plaid-python), and
SimpleNamespace matches that "attribute genuinely absent" behavior — a plain
MagicMock would auto-generate a truthy child for any attribute access, which
would silently defeat the getattr(..., None) branches under test.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest
from balanceai_backend.bank_link.link import (
    LinkExitedError,
    _wait_for_finished_session,
    create_hosted_link,
    run_plaid_link_flow,
)
from balanceai_backend.models.plaid_item import PlaidItem

_LINK = "balanceai_backend.bank_link.link"


def _created_request(mock_client):
    return mock_client.link_token_create.call_args.args[0]


class TestCreateHostedLink:
    def _client(self):
        mock_client = MagicMock()
        mock_client.link_token_create.return_value = SimpleNamespace(
            link_token="link-tok-1", hosted_link_url="https://hosted.plaid.com/abc"
        )
        return mock_client

    def test_returns_link_token_and_hosted_url(self):
        mock_client = self._client()
        with patch(f"{_LINK}.get_client", return_value=mock_client):
            assert create_hosted_link() == ("link-tok-1", "https://hosted.plaid.com/abc")

    def test_a_first_link_asks_for_transactions(self):
        mock_client = self._client()
        with patch(f"{_LINK}.get_client", return_value=mock_client):
            create_hosted_link()
        request = _created_request(mock_client)
        assert [p.value for p in request.products] == ["transactions"]
        assert "access_token" not in request

    def test_update_mode_sends_the_access_token_and_no_products(self):
        mock_client = self._client()
        with patch(f"{_LINK}.get_client", return_value=mock_client):
            create_hosted_link(item=PlaidItem(item_id="item-1", access_token="access-1"))
        request = _created_request(mock_client)
        assert request.access_token == "access-1"
        assert "products" not in request
        assert "update" not in request

    def test_add_accounts_turns_on_the_account_picker(self):
        mock_client = self._client()
        with patch(f"{_LINK}.get_client", return_value=mock_client):
            create_hosted_link(
                item=PlaidItem(item_id="item-1", access_token="access-1"), add_accounts=True
            )
        assert _created_request(mock_client).update.account_selection_enabled is True


def _session(session_id="s1", finished=True, public_token=None, institution=None, exit=None):
    """A fake Hosted Link session. Optional fields are left off entirely when
    unset, as Plaid's SDK models do."""
    fields: dict = {"link_session_id": session_id}
    if finished:
        fields["finished_at"] = "2026-11-21T10:00:00Z"
    if public_token is not None:
        fields["results"] = SimpleNamespace(
            item_add_results=[
                SimpleNamespace(public_token=public_token, institution=institution, accounts=[])
            ]
        )
    if exit is not None:
        fields["exit"] = exit
    return SimpleNamespace(**fields)


def _polls(*sessions_per_poll):
    """link_token_get responses, one per poll."""
    return [SimpleNamespace(link_sessions=list(s)) for s in sessions_per_poll]


def _run(mock_client, **kwargs):
    mock_client.link_token_create.return_value = SimpleNamespace(
        link_token="link-tok-1", hosted_link_url="https://hosted.plaid.com/abc"
    )
    mock_client.item_public_token_exchange.return_value = SimpleNamespace(
        item_id="item-new", access_token="access-new"
    )
    with (
        patch(f"{_LINK}.get_client", return_value=mock_client),
        patch(f"{_LINK}.anyio.sleep", new_callable=AsyncMock),
        patch(f"{_LINK}.webbrowser.open"),
    ):
        return asyncio.run(run_plaid_link_flow(**kwargs))


class TestRunPlaidLinkFlow:
    def test_a_first_link_exchanges_the_public_token_for_a_new_item(self):
        mock_client = MagicMock()
        institution = SimpleNamespace(institution_id="ins_3", name="Tartan Bank")
        mock_client.link_token_get.side_effect = _polls(
            [_session(public_token="public-1", institution=institution)]
        )

        item = _run(mock_client)

        mock_client.item_public_token_exchange.assert_called_once()
        assert mock_client.item_public_token_exchange.call_args.args[0].public_token == "public-1"
        assert (item.item_id, item.access_token) == ("item-new", "access-new")
        assert (item.institution_id, item.institution_name) == ("ins_3", "Tartan Bank")

    def test_a_missing_institution_is_left_empty(self):
        mock_client = MagicMock()
        mock_client.link_token_get.side_effect = _polls([_session(public_token="public-1")])
        item = _run(mock_client)
        assert (item.institution_id, item.institution_name) == (None, None)

    def test_a_result_filled_in_after_finishing_is_picked_up(self):
        mock_client = MagicMock()
        mock_client.link_token_get.side_effect = _polls(
            [_session()], [_session(public_token="public-1")]
        )
        assert _run(mock_client).item_id == "item-new"

    def test_no_result_after_finishing_raises(self):
        mock_client = MagicMock()
        mock_client.link_token_get.side_effect = _polls([_session()], [_session()])
        with pytest.raises(LinkExitedError, match="without linking a bank"):
            _run(mock_client)

    def test_the_second_look_reads_the_same_session_not_a_newer_one(self):
        mock_client = MagicMock()
        mock_client.link_token_get.side_effect = _polls(
            [_session("s1")],
            [_session("s1", public_token="public-1"), _session("s2", finished=False)],
        )
        _run(mock_client)
        assert mock_client.item_public_token_exchange.call_args.args[0].public_token == "public-1"

    def test_update_mode_returns_the_same_item_without_exchanging(self):
        mock_client = MagicMock()
        mock_client.link_token_get.side_effect = _polls([_session()])
        stored = PlaidItem(item_id="item-1", access_token="access-1")

        assert _run(mock_client, item=stored) is stored
        mock_client.item_public_token_exchange.assert_not_called()

    def test_still_runs_when_no_browser_can_be_opened(self):
        import webbrowser

        mock_client = MagicMock()
        mock_client.link_token_create.return_value = SimpleNamespace(
            link_token="link-tok-1", hosted_link_url="https://hosted.plaid.com/abc"
        )
        mock_client.link_token_get.side_effect = _polls([_session()])
        stored = PlaidItem(item_id="item-1", access_token="access-1")
        with (
            patch(f"{_LINK}.get_client", return_value=mock_client),
            patch(f"{_LINK}.anyio.sleep", new_callable=AsyncMock),
            patch(f"{_LINK}.webbrowser.open", side_effect=webbrowser.Error("no browser")),
        ):
            assert asyncio.run(run_plaid_link_flow(item=stored)) is stored


class TestWaitForFinishedSession:
    def _wait(self, mock_client, timeout_s=10):
        with (
            patch(f"{_LINK}.get_client", return_value=mock_client),
            patch(f"{_LINK}.anyio.sleep", new_callable=AsyncMock),
        ):
            return asyncio.run(_wait_for_finished_session("link-tok-1", timeout_s))

    def test_keeps_waiting_before_any_session_exists(self):
        """link_sessions itself is unset until the user opens the page (seen
        live in Sandbox)."""
        mock_client = MagicMock()
        mock_client.link_token_get.side_effect = [SimpleNamespace(), *_polls([_session()])]
        assert self._wait(mock_client).link_session_id == "s1"
        assert mock_client.link_token_get.call_count == 2

    def test_keeps_waiting_while_in_progress(self):
        mock_client = MagicMock()
        mock_client.link_token_get.side_effect = _polls([_session(finished=False)], [_session()])
        assert self._wait(mock_client).link_session_id == "s1"

    def test_an_exit_raises_with_plaids_message(self):
        exit_info = SimpleNamespace(error=SimpleNamespace(error_message="user closed the window"))
        mock_client = MagicMock()
        mock_client.link_token_get.side_effect = _polls([_session(exit=exit_info)])
        with pytest.raises(LinkExitedError, match="user closed the window"):
            self._wait(mock_client)

    def test_an_exit_without_detail_raises_a_default_message(self):
        mock_client = MagicMock()
        mock_client.link_token_get.side_effect = _polls([_session(exit=SimpleNamespace())])
        with pytest.raises(LinkExitedError, match="user exited Hosted Link"):
            self._wait(mock_client)

    def test_an_older_exited_session_doesnt_end_a_newer_one(self):
        exited = _session("s1", exit=SimpleNamespace())
        mock_client = MagicMock()
        mock_client.link_token_get.side_effect = _polls(
            [exited, _session("s2", finished=False)], [exited, _session("s2")]
        )
        assert self._wait(mock_client).link_session_id == "s2"

    def test_times_out(self):
        mock_client = MagicMock()
        mock_client.link_token_get.return_value = SimpleNamespace(
            link_sessions=[_session(finished=False)]
        )
        with pytest.raises(TimeoutError, match="Timed out after"):
            self._wait(mock_client, timeout_s=0)


class TestWaitingDoesntBlock:
    """The wait yields between polls: other tool calls run meanwhile, and a
    cancelled tool call stops polling."""

    def _never_finishing_client(self):
        mock_client = MagicMock()
        mock_client.link_token_get.return_value = SimpleNamespace(
            link_sessions=[_session(finished=False)]
        )
        return mock_client

    def test_other_tasks_run_while_waiting(self):
        mock_client = self._never_finishing_client()
        ticks = []

        async def scenario():
            async def tick():
                while True:
                    ticks.append(1)
                    await anyio.sleep(0.01)

            async with anyio.create_task_group() as tg:
                tg.start_soon(tick)
                with pytest.raises(TimeoutError):
                    await _wait_for_finished_session("link-tok-1", 0.2)
                tg.cancel_scope.cancel()

        with (
            patch(f"{_LINK}.get_client", return_value=mock_client),
            patch(f"{_LINK}._POLL_INTERVAL_S", 0.02),
        ):
            asyncio.run(scenario())
        assert len(ticks) > 5

    def test_cancelling_stops_polling(self):
        mock_client = self._never_finishing_client()

        async def scenario():
            with anyio.move_on_after(0.1):
                await _wait_for_finished_session("link-tok-1", 60)
            polls_at_cancel = mock_client.link_token_get.call_count
            await anyio.sleep(0.1)
            return polls_at_cancel

        with (
            patch(f"{_LINK}.get_client", return_value=mock_client),
            patch(f"{_LINK}._POLL_INTERVAL_S", 0.02),
        ):
            polls_at_cancel = asyncio.run(scenario())
        assert polls_at_cancel > 0
        assert mock_client.link_token_get.call_count == polls_at_cancel
