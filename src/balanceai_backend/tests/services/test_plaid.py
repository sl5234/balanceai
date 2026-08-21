"""Tests for the Plaid client factory."""

from unittest.mock import patch

import pytest
from balanceai_backend.services.plaid import get_client


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
