"""Tests for the Plaid client factory and /accounts/get wrapper.

Fake Plaid response objects use SimpleNamespace rather than MagicMock: Plaid's
real SDK models raise ApiAttributeError on unset optional fields, and
SimpleNamespace matches that "attribute genuinely absent" behavior.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from balanceai_backend.services.plaid import PlaidAccount, get_accounts, get_client


@pytest.fixture(autouse=True)
def _clear_cache():
    """get_client is lru_cache'd — clear it before and after each test so
    settings mocked in one test never leak into another via a cached client."""
    get_client.cache_clear()
    yield
    get_client.cache_clear()


class TestGetClient:
    def test_missing_client_id_raises(self):
        with patch("balanceai_backend.services.plaid.settings") as mock_settings:
            mock_settings.plaid_client_id = None
            mock_settings.plaid_secret = "secret"
            with pytest.raises(ValueError, match="PLAID_CLIENT_ID"):
                get_client()

    def test_missing_secret_raises(self):
        with patch("balanceai_backend.services.plaid.settings") as mock_settings:
            mock_settings.plaid_client_id = "client-id"
            mock_settings.plaid_secret = None
            with pytest.raises(ValueError, match="PLAID_SECRET"):
                get_client()

    def test_unknown_env_raises(self):
        with patch("balanceai_backend.services.plaid.settings") as mock_settings:
            mock_settings.plaid_client_id = "client-id"
            mock_settings.plaid_secret = "secret"
            mock_settings.plaid_env = "staging"
            with pytest.raises(ValueError, match="Unknown PLAID_ENV 'staging'"):
                get_client()

    def test_builds_client_with_sandbox_host(self):
        with patch("balanceai_backend.services.plaid.settings") as mock_settings:
            mock_settings.plaid_client_id = "client-id"
            mock_settings.plaid_secret = "secret"
            mock_settings.plaid_env = "sandbox"
            client = get_client()
            assert client.api_client.configuration.host == "https://sandbox.plaid.com"

    def test_builds_client_with_production_host(self):
        with patch("balanceai_backend.services.plaid.settings") as mock_settings:
            mock_settings.plaid_client_id = "client-id"
            mock_settings.plaid_secret = "secret"
            mock_settings.plaid_env = "production"
            client = get_client()
            assert client.api_client.configuration.host == "https://production.plaid.com"

    def test_env_is_case_insensitive(self):
        with patch("balanceai_backend.services.plaid.settings") as mock_settings:
            mock_settings.plaid_client_id = "client-id"
            mock_settings.plaid_secret = "secret"
            mock_settings.plaid_env = "SANDBOX"
            client = get_client()
            assert client.api_client.configuration.host == "https://sandbox.plaid.com"

    def test_caches_client_across_calls(self):
        with patch("balanceai_backend.services.plaid.settings") as mock_settings:
            mock_settings.plaid_client_id = "client-id"
            mock_settings.plaid_secret = "secret"
            mock_settings.plaid_env = "sandbox"
            first = get_client()
            second = get_client()
            assert first is second


class TestGetAccounts:
    def _get_accounts(self, accounts):
        mock_client = MagicMock()
        mock_client.accounts_get.return_value = SimpleNamespace(accounts=accounts)
        with patch("balanceai_backend.services.plaid.get_client", return_value=mock_client):
            result = get_accounts("access-sandbox-abc")
        return result, mock_client

    def test_returns_accounts_as_plain_data(self):
        result, mock_client = self._get_accounts(
            [
                SimpleNamespace(
                    account_id="plaid-acc-1",
                    name="Plaid Checking",
                    type=SimpleNamespace(value="depository"),
                    subtype=SimpleNamespace(value="checking"),
                    mask="0000",
                )
            ]
        )

        assert result == [
            PlaidAccount(
                account_id="plaid-acc-1",
                name="Plaid Checking",
                type="depository",
                subtype="checking",
                mask="0000",
            )
        ]
        request = mock_client.accounts_get.call_args[0][0]
        assert request.access_token == "access-sandbox-abc"

    def test_missing_optional_fields_come_back_as_none(self):
        result, _ = self._get_accounts([SimpleNamespace(account_id="plaid-acc-1")])

        assert result == [
            PlaidAccount(account_id="plaid-acc-1", name=None, type=None, subtype=None, mask=None)
        ]

    def test_returns_empty_list_when_no_accounts(self):
        result, _ = self._get_accounts([])
        assert result == []
