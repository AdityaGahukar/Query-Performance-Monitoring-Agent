"""
POV-4: Base LLM Provider Abstraction.

Defines the abstract interface for LLM operations and custom analysis exceptions.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LLMAnalysisError(Exception):
    """Base exception for all Analysis Engine errors."""
    pass


class LLMProviderError(LLMAnalysisError):
    """Raised when the provider API returns errors (rate limits, bad keys, API failure)."""
    pass


class LLMTimeoutError(LLMAnalysisError):
    """Raised when the LLM connection or response times out."""
    pass


class LLMValidationError(LLMAnalysisError):
    """Raised when the LLM output fails Pydantic schema validation after retries."""
    pass


# ---------------------------------------------------------------------------
# Abstract Base Provider
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    """
    Abstract interface for LLM provider wrappers.
    Enables future provider extensions (OpenRouter, Bedrock, etc.) without altering agents.
    """

    @abstractmethod
    def generate(
        self,
        system_instruction: str,
        user_prompt: str,
        response_schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.0,
        timeout_seconds: int = 60,
    ) -> Dict[str, Any] | str:
        """
        Submits prompt to provider and returns either a parsed dictionary
        conforming to response_schema or a raw text string.
        """
        pass
