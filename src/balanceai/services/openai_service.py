import base64

from openai import OpenAI

from balanceai.config import settings


def response(
    model_id: str,
    content: str | bytes,
    system_instruction: str | None = None,
    mime_type: str = "image/jpeg",
    max_output_tokens: int = 1024,
    temperature: float = 0.7,
) -> str:
    """
    Send a request to an OpenAI model using the Responses API.

    Args:
        model_id: Model identifier (e.g., 'gpt-4o')
        content: Text string or raw image bytes
        system_instruction: Optional system-level instructions
        mime_type: MIME type of the image when content is bytes
        max_output_tokens: Maximum tokens in response
        temperature: Sampling temperature

    Returns:
        The model's response text
    """
    client = OpenAI(api_key=settings.openai_api_key)

    if isinstance(content, bytes):
        b64 = base64.b64encode(content).decode("utf-8")
        input_content = [
            {"type": "input_image", "image_url": f"data:{mime_type};base64,{b64}"},
        ]
    else:
        input_content = [{"type": "input_text", "text": content}]

    user_input = [{"role": "user", "content": input_content}]

    resp = client.responses.create(
        model=model_id,
        instructions=system_instruction,
        input=user_input,
        response_format={"type": "json_object"},
        max_output_tokens=max_output_tokens,
        temperature=temperature,
    )

    return resp.output_text
