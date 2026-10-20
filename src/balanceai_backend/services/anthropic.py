import base64
from typing import Literal

import anthropic
from anthropic.types import ImageBlockParam, TextBlock, TextBlockParam
from balanceai_backend.config import settings
from pydantic import BaseModel

ImageMimeType = Literal["image/jpeg", "image/png", "image/gif", "image/webp"]


def messages(
    model_id: str,
    content: str | bytes,
    system_instruction: str | None = None,
    mime_type: ImageMimeType = "image/jpeg",
    max_output_tokens: int = 1024,
    temperature: float = 0.7,
) -> str:
    """
    Send a messages request to an Anthropic Claude model.

    Args:
        model_id: Model identifier (e.g., 'claude-sonnet-4-6')
        content: Text string or raw image bytes
        system_instruction: Optional system-level instructions
        mime_type: MIME type of the image when content is bytes
        max_output_tokens: Maximum tokens in response
        temperature: Sampling temperature

    Returns:
        The model's response text
    """
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    input_content: list[TextBlockParam | ImageBlockParam]
    if isinstance(content, bytes):
        b64 = base64.b64encode(content).decode("utf-8")
        input_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime_type,
                    "data": b64,
                },
            }
        ]
    else:
        input_content = [{"type": "text", "text": content}]

    resp = client.messages.create(
        model=model_id,
        max_tokens=max_output_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": input_content}],
        system=system_instruction if system_instruction is not None else anthropic.omit,
    )

    block = resp.content[0]
    if not isinstance(block, TextBlock):
        raise TypeError(f"Expected a text response block, got {type(block).__name__}")
    return block.text


def parse[ParsedT: BaseModel](
    model_id: str,
    content: str,
    output_format: type[ParsedT],
    system_instruction: str | None = None,
    max_output_tokens: int = 1024,
    temperature: float = 0.7,
    timeout: float = 60.0,
) -> ParsedT | None:
    """
    Send a text request and get the reply as an instance of output_format.

    Uses structured outputs, so the API guarantees the reply matches
    output_format's schema. Doesn't retry on its own (max_retries=0) — callers
    that want retries handle them, so they control the policy.

    timeout: seconds to wait for the reply before giving up on this attempt
    (raises anthropic.APITimeoutError).

    Returns:
        The parsed reply, or None if the model declined to answer.
    """
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=0, timeout=timeout)
    resp = client.messages.parse(
        model=model_id,
        max_tokens=max_output_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": content}],
        system=system_instruction if system_instruction is not None else anthropic.omit,
        output_format=output_format,
    )
    return resp.parsed_output
