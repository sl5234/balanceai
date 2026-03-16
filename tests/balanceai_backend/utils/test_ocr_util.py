import json
import sys
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ValidationError

# anthropic is not installed in the test environment — stub it out so that
# balanceai.services.anthropic_service can be imported and patched.
sys.modules.setdefault("anthropic", MagicMock())

from balanceai_backend.utils.ocr_util import OcrUtil, _extract_json


class SampleOutput(BaseModel):
    name: str
    amount: float


class TestExtractJson:
    def test_plain_json(self):
        assert _extract_json('{"name": "test"}') == '{"name": "test"}'

    def test_fenced_with_language_tag(self):
        text = '```json\n{"name": "test"}\n```'
        assert _extract_json(text) == '{"name": "test"}'

    def test_fenced_without_language_tag(self):
        text = '```\n{"name": "test"}\n```'
        assert _extract_json(text) == '{"name": "test"}'

    def test_whitespace_around_fences(self):
        text = '  \n```json\n{"name": "test"}\n```\n  '
        assert _extract_json(text) == '{"name": "test"}'

    def test_multiline_json_in_fences(self):
        text = '```json\n{\n  "name": "test",\n  "amount": 1.0\n}\n```'
        assert _extract_json(text) == '{\n  "name": "test",\n  "amount": 1.0\n}'


# ---------------------------------------------------------------------------
# executeWithAnthropic
# ---------------------------------------------------------------------------


class TestOcrUtilAnthropicText:
    @patch("balanceai.utils.ocr_util.anthropic.messages")
    def test_text_content_returns_valid_model(self, mock_messages):
        mock_messages.return_value = '{"name": "Coffee Shop", "amount": 4.50}'

        result = OcrUtil.executeWithAnthropic(content="some receipt text", output_format=SampleOutput)

        assert isinstance(result, SampleOutput)
        assert result.name == "Coffee Shop"
        assert result.amount == 4.50

    @patch("balanceai.utils.ocr_util.anthropic.messages")
    def test_fenced_response_parses_correctly(self, mock_messages):
        mock_messages.return_value = '```json\n{"name": "Tea", "amount": 3.00}\n```'

        result = OcrUtil.executeWithAnthropic(content="receipt text", output_format=SampleOutput)

        assert result.name == "Tea"
        assert result.amount == 3.00


class TestOcrUtilAnthropicImage:
    @patch("balanceai.utils.ocr_util.anthropic.messages")
    def test_bytes_content_returns_valid_model(self, mock_messages):
        mock_messages.return_value = '{"name": "Grocery", "amount": 25.00}'

        result = OcrUtil.executeWithAnthropic(
            content=b"\x89PNG\r\n",
            output_format=SampleOutput,
            mime_type="image/png",
        )

        assert isinstance(result, SampleOutput)
        assert result.name == "Grocery"
        assert result.amount == 25.00

    @patch("balanceai.utils.ocr_util.anthropic.messages")
    def test_bytes_passes_mime_type(self, mock_messages):
        mock_messages.return_value = '{"name": "x", "amount": 0}'

        OcrUtil.executeWithAnthropic(content=b"\xff\xd8", output_format=SampleOutput, mime_type="image/jpeg")

        assert mock_messages.call_args.kwargs["mime_type"] == "image/jpeg"


class TestOcrUtilAnthropicArgumentPassing:
    @patch("balanceai.utils.ocr_util.anthropic.messages")
    def test_default_model_id(self, mock_messages):
        mock_messages.return_value = '{"name": "x", "amount": 0}'

        OcrUtil.executeWithAnthropic(content="text", output_format=SampleOutput)

        assert mock_messages.call_args.kwargs["model_id"] == "claude-sonnet-4-6"

    @patch("balanceai.utils.ocr_util.anthropic.messages")
    def test_custom_model_id(self, mock_messages):
        mock_messages.return_value = '{"name": "x", "amount": 0}'

        OcrUtil.executeWithAnthropic(content="text", output_format=SampleOutput, model_id="claude-opus-4-6")

        assert mock_messages.call_args.kwargs["model_id"] == "claude-opus-4-6"

    @patch("balanceai.utils.ocr_util.anthropic.messages")
    def test_system_instruction_contains_schema(self, mock_messages):
        mock_messages.return_value = '{"name": "x", "amount": 0}'

        OcrUtil.executeWithAnthropic(content="text", output_format=SampleOutput)

        system_instruction = mock_messages.call_args.kwargs["system_instruction"]
        expected_schema = json.dumps(SampleOutput.model_json_schema(), indent=2)
        assert expected_schema in system_instruction


class TestOcrUtilAnthropicErrors:
    @patch("balanceai.utils.ocr_util.anthropic.messages")
    def test_invalid_json_raises(self, mock_messages):
        mock_messages.return_value = "not valid json at all"

        with pytest.raises(ValidationError):
            OcrUtil.executeWithAnthropic(content="text", output_format=SampleOutput)

    @patch("balanceai.utils.ocr_util.anthropic.messages")
    def test_wrong_schema_raises(self, mock_messages):
        mock_messages.return_value = '{"wrong_field": "value"}'

        with pytest.raises(ValidationError):
            OcrUtil.executeWithAnthropic(content="text", output_format=SampleOutput)
