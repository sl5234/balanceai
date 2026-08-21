"""Tests for the Plaid Hosted Link handshake.

Fake Plaid response objects use SimpleNamespace rather than MagicMock: Plaid's
real generated SDK models raise ApiAttributeError on unset optional fields
instead of returning None (verified against the installed plaid-python), and
SimpleNamespace matches that "attribute genuinely absent" behavior — a plain
MagicMock would auto-generate a truthy child for any attribute access, which
would silently defeat the getattr(..., None) branches under test.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from balanceai_backend.bank_link.link import (
    LinkExitedError,
    complete_link,
    create_hosted_link,
    poll_for_public_token,
)


class TestCreateHostedLink:
    def test_returns_link_token_and_hosted_url(self):
        mock_client = MagicMock()
        mock_client.link_token_create.return_value = SimpleNamespace(
            link_token="link-tok-1",
            hosted_link_url="https://hosted.plaid.com/abc",
        )
        with patch("balanceai_backend.bank_link.link.get_client", return_value=mock_client):
            link_token, hosted_link_url = create_hosted_link()

        assert link_token == "link-tok-1"
        assert hosted_link_url == "https://hosted.plaid.com/abc"
        mock_client.link_token_create.assert_called_once()


def _success_session(public_token="public-tok-1", institution=None, accounts=None):
    """Matches a real Plaid Sandbox Hosted Link success response, verified
    live: session.on_success is never populated despite the SDK's model
    schema advertising it — the actual success signal is
    session.results.item_add_results[0]."""
    item_add_result = SimpleNamespace(
        public_token=public_token, institution=institution, accounts=accounts or []
    )
    return SimpleNamespace(results=SimpleNamespace(item_add_results=[item_add_result]))


class TestPollForPublicToken:
    def test_polls_again_when_link_sessions_entirely_absent(self):
        """Regression test: LinkTokenGetResponse.link_sessions is itself an
        optional field that raises ApiAttributeError when unset (confirmed
        against a real Plaid sandbox call — link_sessions isn't populated
        until session activity exists yet), not just the fields nested
        inside each session."""
        no_sessions_yet = SimpleNamespace()  # no .link_sessions attribute at all
        mock_client = MagicMock()
        mock_client.link_token_get.side_effect = [
            no_sessions_yet,
            SimpleNamespace(link_sessions=[_success_session()]),
        ]

        with (
            patch("balanceai_backend.bank_link.link.get_client", return_value=mock_client),
            patch("balanceai_backend.bank_link.link.time.sleep"),
        ):
            public_token, _ = poll_for_public_token("link-tok-1", timeout_s=10)

        assert public_token == "public-tok-1"
        assert mock_client.link_token_get.call_count == 2

    def test_returns_public_token_on_first_success(self):
        institution = SimpleNamespace(institution_id="ins_3", name="Chase")
        mock_client = MagicMock()
        mock_client.link_token_get.return_value = SimpleNamespace(
            link_sessions=[_success_session(institution=institution)]
        )

        with patch("balanceai_backend.bank_link.link.get_client", return_value=mock_client):
            public_token, item_add_result = poll_for_public_token("link-tok-1", timeout_s=10)

        assert public_token == "public-tok-1"
        assert item_add_result.institution is institution

    def test_polls_again_when_pending_then_succeeds(self):
        pending_session = SimpleNamespace(link_session_id="s1")  # no results, no exit yet
        mock_client = MagicMock()
        mock_client.link_token_get.side_effect = [
            SimpleNamespace(link_sessions=[pending_session]),
            SimpleNamespace(link_sessions=[_success_session()]),
        ]

        with (
            patch("balanceai_backend.bank_link.link.get_client", return_value=mock_client),
            patch("balanceai_backend.bank_link.link.time.sleep"),
        ):
            public_token, _ = poll_for_public_token("link-tok-1", timeout_s=10)

        assert public_token == "public-tok-1"
        assert mock_client.link_token_get.call_count == 2

    def test_raises_link_exited_error_on_exit(self):
        session = SimpleNamespace(
            exit=SimpleNamespace(error=SimpleNamespace(error_message="user closed the window"))
        )
        mock_client = MagicMock()
        mock_client.link_token_get.return_value = SimpleNamespace(link_sessions=[session])

        with (
            patch("balanceai_backend.bank_link.link.get_client", return_value=mock_client),
            pytest.raises(LinkExitedError, match="user closed the window"),
        ):
            poll_for_public_token("link-tok-1", timeout_s=10)

    def test_raises_link_exited_error_with_default_message_when_no_error_detail(self):
        session = SimpleNamespace(exit=SimpleNamespace())  # exit present, but no .error
        mock_client = MagicMock()
        mock_client.link_token_get.return_value = SimpleNamespace(link_sessions=[session])

        with (
            patch("balanceai_backend.bank_link.link.get_client", return_value=mock_client),
            pytest.raises(LinkExitedError, match="user exited Hosted Link"),
        ):
            poll_for_public_token("link-tok-1", timeout_s=10)

    def test_times_out_when_never_resolved(self):
        pending_session = SimpleNamespace(link_session_id="s1")
        mock_client = MagicMock()
        mock_client.link_token_get.return_value = SimpleNamespace(link_sessions=[pending_session])

        with (
            patch("balanceai_backend.bank_link.link.get_client", return_value=mock_client),
            patch("balanceai_backend.bank_link.link.time.sleep"),
            pytest.raises(TimeoutError, match="Timed out after"),
        ):
            poll_for_public_token("link-tok-1", timeout_s=0)


class TestCompleteLink:
    def _metadata(self, institution=None, accounts=None):
        return SimpleNamespace(institution=institution, accounts=accounts)

    def test_saves_and_returns_plaid_item(self):
        metadata = self._metadata(
            institution=SimpleNamespace(institution_id="ins_3", name="Chase"),
            accounts=[SimpleNamespace(id="plaid-acc-1"), SimpleNamespace(id="plaid-acc-2")],
        )
        mock_client = MagicMock()
        mock_client.item_public_token_exchange.return_value = SimpleNamespace(
            item_id="item-1", access_token="access-sandbox-abc"
        )

        with (
            patch("balanceai_backend.bank_link.link.get_client", return_value=mock_client),
            patch(
                "balanceai_backend.bank_link.link.poll_for_public_token",
                return_value=("public-tok-1", metadata),
            ),
            patch("balanceai_backend.bank_link.link.save_plaid_item") as mock_save,
        ):
            item = complete_link("link-tok-1")

        assert item.item_id == "item-1"
        assert item.access_token == "access-sandbox-abc"
        assert item.institution_id == "ins_3"
        assert item.institution_name == "Chase"
        assert item.plaid_account_ids == ["plaid-acc-1", "plaid-acc-2"]
        assert item.our_account_ids == []
        mock_save.assert_called_once_with(item)

    def test_handles_missing_institution_and_accounts_gracefully(self):
        metadata = self._metadata(institution=None, accounts=None)
        mock_client = MagicMock()
        mock_client.item_public_token_exchange.return_value = SimpleNamespace(
            item_id="item-1", access_token="access-sandbox-abc"
        )

        with (
            patch("balanceai_backend.bank_link.link.get_client", return_value=mock_client),
            patch(
                "balanceai_backend.bank_link.link.poll_for_public_token",
                return_value=("public-tok-1", metadata),
            ),
            patch("balanceai_backend.bank_link.link.save_plaid_item"),
        ):
            item = complete_link("link-tok-1")

        assert item.institution_id is None
        assert item.institution_name is None
        assert item.plaid_account_ids == []
