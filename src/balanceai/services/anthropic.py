import base64

import anthropic

from balanceai.config import settings


def messages(
    model_id: str,
    content: str | bytes,
    system_instruction: str | None = None,
    mime_type: str = "image/jpeg",
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

    kwargs = dict(
        model=model_id,
        max_tokens=max_output_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": input_content}],
    )
    if system_instruction is not None:
        kwargs["system"] = system_instruction

    resp = client.messages.create(**kwargs)

    return resp.content[0].text
