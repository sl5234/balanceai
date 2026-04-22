from typing import Optional

from google import genai
from google.genai.types import GenerateContentResponse

from balanceai_backend.config import settings

DEFAULT_MODEL_ID = "gemini-2.5-flash-lite"
# DEFAULT_MODEL_ID = "gemini-2.5-flash"


class GeminiClient:
    """Client for interacting with Google's Gemini API."""

    def __init__(self, api_key: Optional[str] = None, model_id: Optional[str] = None):
        """Initialize the Gemini client.

        Args:
            api_key: Gemini API key. Defaults to the KMS-decrypted key from settings.
            model_id: The Gemini model to use.
        """
        self.client = genai.Client(api_key=api_key or settings.gemini_api_key)
        self.model_id = model_id if model_id is not None else DEFAULT_MODEL_ID

    def converse(
        self,
        user_message: str,
        system_prompt: str,
        max_tokens: int = 1024,
    ) -> str:
        """Send a message to Gemini and return the response text.

        Args:
            user_message: The user message to send.
            system_prompt: The system prompt to guide the model.
            max_tokens: Maximum tokens in the response.

        Returns:
            The text content from the model response.
        """
        response: GenerateContentResponse = self.client.models.generate_content(
            model=self.model_id,
            contents=user_message,
            config={
                "system_instruction": system_prompt,
                "max_output_tokens": max_tokens,
            },
        )
        result: str = response.text  # type: ignore[assignment]
        return result


def converse(
    client: GeminiClient,
    user_message: str,
    system_prompt: str,
    max_tokens: int = 1024,
) -> str:
    """Call Gemini API and return the response text.

    Args:
        client: GeminiClient instance.
        user_message: The user message to send.
        system_prompt: The system prompt to guide the model.
        max_tokens: Maximum tokens in the response.

    Returns:
        The text content from the model response.
    """
    return client.converse(
        user_message=user_message,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
    )
