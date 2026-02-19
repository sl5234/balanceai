import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ValidationError

from balanceai.utils.ocr_util import OcrUtil, _extract_json


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
# executeWithGcpVertexAi
# ---------------------------------------------------------------------------

class TestOcrUtilGcpText:
    @patch("balanceai.utils.ocr_util.generate_content")
    @patch("balanceai.utils.ocr_util.Part")
    def test_text_content_returns_valid_model(self, mock_part, mock_generate):
        mock_generate.return_value = '{"name": "Coffee Shop", "amount": 4.50}'
        mock_part.from_text.return_value = MagicMock()

        result = OcrUtil.executeWithGcpVertexAi(content="some receipt text", output_format=SampleOutput)

        assert isinstance(result, SampleOutput)
        assert result.name == "Coffee Shop"
        assert result.amount == 4.50

    @patch("balanceai.utils.ocr_util.generate_content")
    @patch("balanceai.utils.ocr_util.Part")
    def test_text_content_calls_part_from_text(self, mock_part, mock_generate):
        mock_generate.return_value = '{"name": "x", "amount": 0}'

        OcrUtil.executeWithGcpVertexAi(content="hello", output_format=SampleOutput)

        mock_part.from_text.assert_called_once_with("hello")
        mock_part.from_data.assert_not_called()

    @patch("balanceai.utils.ocr_util.generate_content")
    @patch("balanceai.utils.ocr_util.Part")
    def test_fenced_response_parses_correctly(self, mock_part, mock_generate):
        mock_generate.return_value = '```json\n{"name": "Tea", "amount": 3.00}\n```'

        result = OcrUtil.executeWithGcpVertexAi(content="receipt text", output_format=SampleOutput)

        assert result.name == "Tea"
        assert result.amount == 3.00


class TestOcrUtilGcpImage:
    @patch("balanceai.utils.ocr_util.generate_content")
    @patch("balanceai.utils.ocr_util.Part")
    def test_bytes_content_returns_valid_model(self, mock_part, mock_generate):
        mock_generate.return_value = '{"name": "Grocery", "amount": 25.00}'
        mock_part.from_data.return_value = MagicMock()

        result = OcrUtil.executeWithGcpVertexAi(
            content=b"\x89PNG\r\n",
            output_format=SampleOutput,
            mime_type="image/png",
        )

        assert isinstance(result, SampleOutput)
        assert result.name == "Grocery"
        assert result.amount == 25.00

    @patch("balanceai.utils.ocr_util.generate_content")
    @patch("balanceai.utils.ocr_util.Part")
    def test_bytes_content_calls_part_from_data(self, mock_part, mock_generate):
        mock_generate.return_value = '{"name": "x", "amount": 0}'
        image_bytes = b"\xff\xd8\xff\xe0"

        OcrUtil.executeWithGcpVertexAi(content=image_bytes, output_format=SampleOutput, mime_type="image/jpeg")

        mock_part.from_data.assert_called_once_with(data=image_bytes, mime_type="image/jpeg")
        mock_part.from_text.assert_not_called()


class TestOcrUtilGcpArgumentPassing:
    @patch("balanceai.utils.ocr_util.generate_content")
    @patch("balanceai.utils.ocr_util.Part")
    def test_default_model_id(self, mock_part, mock_generate):
        mock_generate.return_value = '{"name": "x", "amount": 0}'

        OcrUtil.executeWithGcpVertexAi(content="text", output_format=SampleOutput)

        assert mock_generate.call_args.kwargs["model_id"] == "gemini-2.0-flash"

    @patch("balanceai.utils.ocr_util.generate_content")
    @patch("balanceai.utils.ocr_util.Part")
    def test_custom_model_id(self, mock_part, mock_generate):
        mock_generate.return_value = '{"name": "x", "amount": 0}'

        OcrUtil.executeWithGcpVertexAi(content="text", output_format=SampleOutput, model_id="gemini-pro")

        assert mock_generate.call_args.kwargs["model_id"] == "gemini-pro"

    @patch("balanceai.utils.ocr_util.generate_content")
    @patch("balanceai.utils.ocr_util.Part")
    def test_system_instruction_contains_schema(self, mock_part, mock_generate):
        mock_generate.return_value = '{"name": "x", "amount": 0}'

        OcrUtil.executeWithGcpVertexAi(content="text", output_format=SampleOutput)

        system_instruction = mock_generate.call_args.kwargs["system_instruction"]
        expected_schema = json.dumps(SampleOutput.model_json_schema(), indent=2)
        assert expected_schema in system_instruction


class TestOcrUtilGcpErrors:
    @patch("balanceai.utils.ocr_util.generate_content")
    @patch("balanceai.utils.ocr_util.Part")
    def test_invalid_json_raises(self, mock_part, mock_generate):
        mock_generate.return_value = "not valid json at all"

        with pytest.raises(ValidationError):
            OcrUtil.executeWithGcpVertexAi(content="text", output_format=SampleOutput)

    @patch("balanceai.utils.ocr_util.generate_content")
    @patch("balanceai.utils.ocr_util.Part")
    def test_wrong_schema_raises(self, mock_part, mock_generate):
        mock_generate.return_value = '{"wrong_field": "value"}'

        with pytest.raises(ValidationError):
            OcrUtil.executeWithGcpVertexAi(content="text", output_format=SampleOutput)


# ---------------------------------------------------------------------------
# executeWithOpenAi
# ---------------------------------------------------------------------------

class TestOcrUtilOpenAiText:
    @patch("balanceai.utils.ocr_util.openai_service.response")
    def test_text_content_returns_valid_model(self, mock_generate):
        mock_generate.return_value = '{"name": "Coffee Shop", "amount": 4.50}'

        result = OcrUtil.executeWithOpenAi(content="some receipt text", output_format=SampleOutput)

        assert isinstance(result, SampleOutput)
        assert result.name == "Coffee Shop"
        assert result.amount == 4.50

    @patch("balanceai.utils.ocr_util.openai_service.response")
    def test_fenced_response_parses_correctly(self, mock_generate):
        mock_generate.return_value = '```json\n{"name": "Tea", "amount": 3.00}\n```'

        result = OcrUtil.executeWithOpenAi(content="receipt text", output_format=SampleOutput)

        assert result.name == "Tea"
        assert result.amount == 3.00


class TestOcrUtilOpenAiImage:
    @patch("balanceai.utils.ocr_util.openai_service.response")
    def test_bytes_content_returns_valid_model(self, mock_generate):
        mock_generate.return_value = '{"name": "Grocery", "amount": 25.00}'

        result = OcrUtil.executeWithOpenAi(
            content=b"\x89PNG\r\n",
            output_format=SampleOutput,
            mime_type="image/png",
        )

        assert isinstance(result, SampleOutput)
        assert result.name == "Grocery"
        assert result.amount == 25.00

    @patch("balanceai.utils.ocr_util.openai_service.response")
    def test_bytes_passes_mime_type(self, mock_generate):
        mock_generate.return_value = '{"name": "x", "amount": 0}'

        OcrUtil.executeWithOpenAi(content=b"\xff\xd8", output_format=SampleOutput, mime_type="image/jpeg")

        assert mock_generate.call_args.kwargs["mime_type"] == "image/jpeg"


class TestOcrUtilOpenAiArgumentPassing:
    @patch("balanceai.utils.ocr_util.openai_service.response")
    def test_default_model_id(self, mock_generate):
        mock_generate.return_value = '{"name": "x", "amount": 0}'

        OcrUtil.executeWithOpenAi(content="text", output_format=SampleOutput)

        assert mock_generate.call_args.kwargs["model_id"] == "gpt-4o"

    @patch("balanceai.utils.ocr_util.openai_service.response")
    def test_custom_model_id(self, mock_generate):
        mock_generate.return_value = '{"name": "x", "amount": 0}'

        OcrUtil.executeWithOpenAi(content="text", output_format=SampleOutput, model_id="gpt-4-turbo")

        assert mock_generate.call_args.kwargs["model_id"] == "gpt-4-turbo"

    @patch("balanceai.utils.ocr_util.openai_service.response")
    def test_system_instruction_contains_schema(self, mock_generate):
        mock_generate.return_value = '{"name": "x", "amount": 0}'

        OcrUtil.executeWithOpenAi(content="text", output_format=SampleOutput)

        system_instruction = mock_generate.call_args.kwargs["system_instruction"]
        expected_schema = json.dumps(SampleOutput.model_json_schema(), indent=2)
        assert expected_schema in system_instruction


class TestOcrUtilOpenAiErrors:
    @patch("balanceai.utils.ocr_util.openai_service.response")
    def test_invalid_json_raises(self, mock_generate):
        mock_generate.return_value = "not valid json at all"

        with pytest.raises(ValidationError):
            OcrUtil.executeWithOpenAi(content="text", output_format=SampleOutput)

    @patch("balanceai.utils.ocr_util.openai_service.response")
    def test_wrong_schema_raises(self, mock_generate):
        mock_generate.return_value = '{"wrong_field": "value"}'

        with pytest.raises(ValidationError):
            OcrUtil.executeWithOpenAi(content="text", output_format=SampleOutput)
