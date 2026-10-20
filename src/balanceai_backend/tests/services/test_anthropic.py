from unittest.mock import MagicMock, patch

from balanceai_backend.services.anthropic import parse
from pydantic import BaseModel


class _Answer(BaseModel):
    value: str


class TestParse:
    def _call(self, parsed_output, **kwargs):
        client = MagicMock()
        client.messages.parse.return_value = MagicMock(parsed_output=parsed_output)
        with patch(
            "balanceai_backend.services.anthropic.anthropic.Anthropic", return_value=client
        ) as client_class:
            result = parse(
                model_id="claude-haiku-4-5", content="hi", output_format=_Answer, **kwargs
            )
        return result, client_class, client.messages.parse.call_args.kwargs

    def test_returns_the_parsed_reply(self):
        result, _, _ = self._call(_Answer(value="ok"))
        assert result == _Answer(value="ok")

    def test_returns_none_when_the_model_declines(self):
        result, _, _ = self._call(None)
        assert result is None

    def test_sends_output_format_and_settings(self):
        _, _, sent = self._call(
            _Answer(value="ok"), system_instruction="sys", max_output_tokens=50, temperature=0.0
        )
        assert sent["output_format"] is _Answer
        assert sent["model"] == "claude-haiku-4-5"
        assert sent["system"] == "sys"
        assert sent["max_tokens"] == 50
        assert sent["temperature"] == 0.0
        assert sent["messages"] == [{"role": "user", "content": "hi"}]

    def test_turns_off_sdk_retries(self):
        _, client_class, _ = self._call(_Answer(value="ok"))
        assert client_class.call_args.kwargs["max_retries"] == 0

    def test_times_out_after_sixty_seconds_by_default(self):
        _, client_class, _ = self._call(_Answer(value="ok"))
        assert client_class.call_args.kwargs["timeout"] == 60.0

    def test_uses_a_given_timeout(self):
        _, client_class, _ = self._call(_Answer(value="ok"), timeout=5.0)
        assert client_class.call_args.kwargs["timeout"] == 5.0
