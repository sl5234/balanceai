from typing import Any

from botocore.client import BaseClient  # type: ignore[import-untyped]


def converse(
    client: BaseClient,
    model_id: str,
    messages: list[dict[str, Any]],
    system_prompt: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
) -> str:
    """
    Send a message to a Bedrock model using the Converse API.

    Args:
        client: Bedrock Runtime client
        model_id: Model identifier (e.g., 'anthropic.claude-3-sonnet-20240229-v1:0')
        messages: List of message dicts with 'role' and 'content' keys
        system_prompt: Optional system prompt
        max_tokens: Maximum tokens in response
        temperature: Sampling temperature

    Returns:
        The model's response text
    """
    request: dict[str, Any] = {
        "modelId": model_id,
        "messages": messages,
        "inferenceConfig": {
            "maxTokens": max_tokens,
            "temperature": temperature,
        },
    }

    if system_prompt:
        request["system"] = [{"text": system_prompt}]

    response = client.converse(**request)

    return response["output"]["message"]["content"][0]["text"]
