"""
POV-4: Google Gemini Provider implementation.

Implements the LLMProvider abstraction using Google Gemini (via LangChain).
"""

import time
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.core.logging import get_logger
from src.agents.providers.base import (
    LLMProvider,
    LLMProviderError,
    LLMTimeoutError,
    LLMValidationError,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Gemini Provider Implementation
# ---------------------------------------------------------------------------

class GeminiProvider(LLMProvider):
    """
    Google Gemini provider wrapper using LangChain's ChatGoogleGenerativeAI.
    """

    def __init__(self, api_key: str, model_name: str = "gemini-3.5-flash"):
        if not api_key:
            raise LLMProviderError("Gemini API key is required but missing.")
        self.api_key = api_key
        self.model_name = model_name

    def generate(
        self,
        system_instruction: str,
        user_prompt: str,
        response_schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.0,
        timeout_seconds: int = 60,
    ) -> Dict[str, Any] | str:
        """
        Executes inference against Google Gemini.
        Utilizes LangChain's structured output bindings when response_schema is provided.
        """
        logger.info("Initializing ChatGoogleGenerativeAI model request", extra={
            "model_name": self.model_name,
            "temperature": temperature,
            "timeout_seconds": timeout_seconds,
            "structured_output": response_schema is not None
        })

        try:
            # Initialize client model
            model = ChatGoogleGenerativeAI(
                model=self.model_name,
                google_api_key=self.api_key,
                temperature=temperature,
                timeout=float(timeout_seconds),
                max_retries=0,  # Retries are managed by the calling Analyzer layer
            )

            messages = [
                SystemMessage(content=system_instruction),
                HumanMessage(content=user_prompt),
            ]

            start_time = time.perf_counter()

            if response_schema:
                # Bind Pydantic output parsing schema
                structured_model = model.with_structured_output(response_schema)
                result = structured_model.invoke(messages)
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                logger.debug("Successfully received structured Gemini response", extra={"latency_ms": latency_ms})
                
                # result is an instantiated Pydantic model
                if isinstance(result, BaseModel):
                    return result.model_dump()
                elif isinstance(result, dict):
                    return result
                else:
                    raise LLMValidationError(f"Expected structured output to parse, got: {type(result)}")
            else:
                result_raw = model.invoke(messages)
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                logger.debug("Successfully received raw Gemini response", extra={"latency_ms": latency_ms})
                return str(result_raw.content)

        except Exception as e:
            err_msg = str(e).lower()
            logger.error("Gemini API call failed", extra={"error": str(e)})

            # Map common errors to domain exceptions
            if "timeout" in err_msg or "timed out" in err_msg or "deadline" in err_msg:
                raise LLMTimeoutError(f"Gemini API request timed out: {e}")
            elif "validation" in err_msg or "pydantic" in err_msg:
                raise LLMValidationError(f"Gemini output parsing/validation failed: {e}")
            else:
                raise LLMProviderError(f"Gemini API call failed with provider error: {e}")
