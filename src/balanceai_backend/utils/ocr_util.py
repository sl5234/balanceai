import json
import logging
from typing import TypeVar

from pydantic import BaseModel

from balanceai_backend.services import anthropic

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

DEFAULT_ANTHROPIC_MODEL_ID = "claude-sonnet-4-6"


class OcrUtil:
    """Utility for extracting structured data from text or images using an LLM."""

    @staticmethod
    def executeWithAnthropic(
        content: str | bytes,
        output_format: type[T],
        mime_type: str = "image/jpeg",
        model_id: str = DEFAULT_ANTHROPIC_MODEL_ID,
    ) -> T:
        """
        Extract structured data from text or image content using Anthropic Claude.

        Args:
            content: Text string or raw image bytes.
            output_format: A Pydantic model class defining the expected output schema.
            mime_type: MIME type of the image when content is bytes.
            model_id: The Anthropic model to use.

        Returns:
            An instance of the output_format Pydantic model.
        """
        schema = json.dumps(output_format.model_json_schema(), indent=2)
        system_instruction = (
            "You are an OCR assistant. Extract the requested information "
            "from the provided content and return it as JSON matching this schema:\n"
            f"{schema}\n\n"
            "Return ONLY valid JSON. No extra text."
        )

        response_text = anthropic.messages(
            model_id=model_id,
            content=content,
            system_instruction=system_instruction,
            mime_type=mime_type,
        )

        cleaned = _extract_json(response_text)
        return output_format.model_validate_json(cleaned)


def _extract_json(text: str) -> str:
    """Strip markdown code fences if present, then extract the outermost JSON object."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return text
