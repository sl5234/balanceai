import base64
from typing import Literal

import anthropic
from anthropic.types import ImageBlockParam, TextBlock, TextBlockParam
from balanceai_backend.config import settings

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
