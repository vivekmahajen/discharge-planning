"""Abstract base class for all discharge planning agents."""
import asyncio
import sys
from abc import ABC, abstractmethod
from functools import partial
from typing import Any

import anthropic


class BaseAgent(ABC):
    """Abstract base class for discharge planning specialist agents.

    Each subclass implements a specific domain of discharge planning assessment
    (clinical, care needs, insurance, medications, or social determinants).
    """

    MODEL = "claude-sonnet-4-6"
    MAX_TOKENS = 4000
    TEMPERATURE = 0.2

    SYSTEM_PROMPT: str = ""

    def __init__(self, client: anthropic.Anthropic) -> None:
        """Initialize the agent with a shared Anthropic client.

        Args:
            client: Authenticated Anthropic SDK client instance.
        """
        self.client = client

    @abstractmethod
    def format_input(self, patient_data: dict) -> str:
        """Format patient data into a structured string for the LLM.

        Args:
            patient_data: Dictionary containing patient information.

        Returns:
            Formatted string ready to be used as user message content.
        """
        ...

    def _sync_create(self, user_message: str) -> str:
        """Execute a synchronous Anthropic API call.

        Args:
            user_message: The formatted user message to send.

        Returns:
            The text content from the model's response.

        Raises:
            anthropic.APIError: If the API call fails.
        """
        response = self.client.messages.create(
            model=self.MODEL,
            max_tokens=self.MAX_TOKENS,
            temperature=self.TEMPERATURE,
            system=self.SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_message},
            ],
        )
        return response.content[0].text

    async def run(self, patient_data: dict) -> str:
        """Run the agent asynchronously against the given patient data.

        Wraps the synchronous Anthropic SDK call using run_in_executor so it
        can be awaited alongside other agents in asyncio.gather().

        Args:
            patient_data: Dictionary containing patient information.

        Returns:
            The agent's structured assessment as a string.

        Raises:
            anthropic.APIError: If the API call fails after formatting input.
        """
        user_message = self.format_input(patient_data)

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, partial(self._sync_create, user_message)
            )
        except anthropic.APIError as exc:
            print(
                f"[ERROR] {self.__class__.__name__} API call failed: {exc}",
                file=sys.stderr,
            )
            raise

        return result
