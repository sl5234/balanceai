"""Tests for the Gemini service."""

import os
from unittest.mock import MagicMock, patch

import pytest

from balanceai_backend.services.gemini import GeminiClient, converse


class TestGeminiClient:
    """Tests for GeminiClient class."""

    def test_init_with_explicit_api_key(self):
        """Test client initialization with explicit API key."""
        with patch("balanceai_backend.services.gemini.genai") as mock_genai:
            client = GeminiClient(api_key="test-key")
            mock_genai.Client.assert_called_once_with(api_key="test-key")
            assert client.model_id == "gemini-2.5-flash-lite"

    def test_init_defaults_to_settings(self):
        """Test client initialization falls back to settings.gemini_api_key."""
        with patch("balanceai_backend.services.gemini.genai") as mock_genai:
            with patch("balanceai_backend.services.gemini.settings") as mock_settings:
                mock_settings.gemini_api_key = "settings-key"
                GeminiClient()
                mock_genai.Client.assert_called_once_with(api_key="settings-key")

    def test_custom_model_id(self):
        """Test client initialization with a custom model ID."""
        with patch("balanceai_backend.services.gemini.genai"):
            with patch("balanceai_backend.services.gemini.settings") as mock_settings:
                mock_settings.gemini_api_key = "test-key"
                client = GeminiClient(model_id="gemini-2.5-pro")
                assert client.model_id == "gemini-2.5-pro"

    def test_converse(self):
        """Test the converse method passes arguments correctly and returns text."""
        with patch("balanceai_backend.services.gemini.genai") as mock_genai:
            mock_response = MagicMock()
            mock_response.text = "Test response"
            mock_genai_instance = MagicMock()
            mock_genai_instance.models.generate_content.return_value = mock_response
            mock_genai.Client.return_value = mock_genai_instance

            client = GeminiClient(api_key="test-key")
            result = client.converse(
                user_message="Hello",
                system_prompt="Be helpful",
                max_tokens=100,
            )

            assert result == "Test response"
            mock_genai_instance.models.generate_content.assert_called_once_with(
                model="gemini-2.5-flash-lite",
                contents="Hello",
                config={
                    "system_instruction": "Be helpful",
                    "max_output_tokens": 100,
                },
            )

    def test_converse_default_max_tokens(self):
        """Test that converse uses 1024 as default max_tokens."""
        with patch("balanceai_backend.services.gemini.genai") as mock_genai:
            mock_response = MagicMock()
            mock_response.text = "response"
            mock_genai_instance = MagicMock()
            mock_genai_instance.models.generate_content.return_value = mock_response
            mock_genai.Client.return_value = mock_genai_instance

            client = GeminiClient(api_key="test-key")
            client.converse(user_message="Hi", system_prompt="prompt")

            call_kwargs = mock_genai_instance.models.generate_content.call_args
            assert call_kwargs.kwargs["config"]["max_output_tokens"] == 1024


class TestConverseFunction:
    """Tests for the standalone converse function."""

    def test_delegates_to_client(self):
        """Test that converse delegates to client.converse with correct args."""
        mock_client = MagicMock(spec=GeminiClient)
        mock_client.converse.return_value = "Function response"

        result = converse(
            client=mock_client,
            user_message="Test message",
            system_prompt="Test prompt",
            max_tokens=512,
        )

        assert result == "Function response"
        mock_client.converse.assert_called_once_with(
            user_message="Test message",
            system_prompt="Test prompt",
            max_tokens=512,
        )

    def test_default_max_tokens(self):
        """Test that converse uses 1024 as default max_tokens."""
        mock_client = MagicMock(spec=GeminiClient)
        mock_client.converse.return_value = "response"

        converse(client=mock_client, user_message="Hi", system_prompt="prompt")

        mock_client.converse.assert_called_once_with(
            user_message="Hi",
            system_prompt="prompt",
            max_tokens=1024,
        )


@pytest.mark.integration
class TestGeminiIntegration:
    """Integration tests that make real API calls to Gemini.

    Run with: pytest -m integration
    Requires GEMINI_API_KEY environment variable to be set.

    Rate limits (gemini-2.5-flash): 20 requests per minute.
    """

    RATE_LIMIT_DELAY = 4  # seconds between calls
    MAX_RETRIES = 3
    RETRY_DELAY = 10  # seconds to wait on rate limit error

    @pytest.fixture
    def client(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            pytest.skip("GEMINI_API_KEY environment variable not set")
        return GeminiClient(api_key=api_key)

    def _call_with_retry(self, func, *args, **kwargs):
        import time
        from google.genai.errors import ClientError

        for attempt in range(self.MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except ClientError as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    if attempt < self.MAX_RETRIES - 1:
                        wait_time = self.RETRY_DELAY * (attempt + 1)
                        print(f"\nRate limited, waiting {wait_time}s before retry...")
                        time.sleep(wait_time)
                    else:
                        raise
                else:
                    raise

    def test_simple_response(self, client):
        """Test that a basic call returns a non-empty response."""
        import time

        response = self._call_with_retry(
            client.converse,
            user_message="What is 2 + 2? Reply with just the number.",
            system_prompt="You are a helpful assistant. Be concise.",
            max_tokens=10,
        )

        assert response is not None
        assert len(response) > 0
        assert "4" in response

        time.sleep(self.RATE_LIMIT_DELAY)

    def test_financial_query_response_format(self, client):
        """Test that Gemini returns valid JSON for a financial analysis question."""
        import json
        import re
        import time
        from datetime import date
        from balanceai_backend.prompts.financial_query_prompt import financial_query_system_prompt

        response = self._call_with_retry(
            client.converse,
            user_message="How much did I spend at Shell in October 2025?",
            system_prompt=financial_query_system_prompt(date.today()),
            max_tokens=1024,
        )

        # Strip markdown code fences if present
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
        json_str = json_match.group(1).strip() if json_match else response.strip()
        parsed = json.loads(json_str)

        assert "sql" in parsed, "Response must contain a 'sql' key"
        assert "description" in parsed, "Response must contain a 'description' key"
        assert parsed["sql"].strip().upper().startswith("SELECT"), "sql must be a SELECT statement"
        # Should filter by recipient, not description
        assert (
            "recipient" in parsed["sql"].lower()
        ), "sql should filter by recipient for merchant queries"

        time.sleep(self.RATE_LIMIT_DELAY)
