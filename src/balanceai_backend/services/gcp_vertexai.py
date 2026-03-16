import os
from typing import Any

import vertexai  # type: ignore[import-untyped]
from vertexai.generative_models import GenerativeModel, Part  # type: ignore[import-untyped]

vertexai.init(
    project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
    location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
)


def generate_content(
    model_id: str,
    contents: list[Part],
    system_instruction: str | None = None,
    max_output_tokens: int = 1024,
    temperature: float = 0.7,
) -> str:
    """
    Send a request to a Gemini model via Vertex AI.

    Args:
        model_id: Model identifier (e.g., 'gemini-2.0-flash')
        contents: List of Part objects (text, images, etc.)
        system_instruction: Optional system instruction
        max_output_tokens: Maximum tokens in response
        temperature: Sampling temperature

    Returns:
        The model's response text
    """
    model = GenerativeModel(
        model_name=model_id,
        system_instruction=system_instruction,
    )

    generation_config: dict[str, Any] = {
        "max_output_tokens": max_output_tokens,
        "temperature": temperature,
    }

    response = model.generate_content(
        contents=contents,
        generation_config=generation_config,
    )

    return response.text
