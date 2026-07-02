"""
POV-4: Nvidia LLM Provider implementation using NVIDIA AI Endpoints.

Implements the LLMProvider abstraction using ChatNVIDIA or direct requests fallback.
"""

import time
import json
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel
from src.core.logging import get_logger
from src.agents.providers.base import (
    LLMProvider,
    LLMAnalysisError,
    LLMProviderError,
    LLMTimeoutError,
    LLMValidationError,
)

logger = get_logger(__name__)

# Try to import langchain-nvidia-ai-endpoints (will succeed locally, fail inside Snowflake)
try:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_nvidia_ai_endpoints import ChatNVIDIA
    HAS_LANGCHAIN_NVIDIA = True
except ImportError:
    HAS_LANGCHAIN_NVIDIA = False


class NvidiaProvider(LLMProvider):
    """
    Nvidia AI Endpoints provider wrapper supporting ChatNVIDIA or raw requests.
    """

    def __init__(self, api_key: str, model_name: str = "meta/llama-3.1-8b-instruct", base_url: Optional[str] = None):
        if not api_key:
            raise LLMProviderError("Nvidia API key is required but missing.")
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url or "https://integrate.api.nvidia.com/v1"

    def generate(
        self,
        system_instruction: str,
        user_prompt: str,
        response_schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.0,
        timeout_seconds: int = 60,
    ) -> Dict[str, Any] | str:
        """
        Executes inference against the active Nvidia Endpoint model.
        Uses ChatNVIDIA locally, and falls back to a direct requests HTTP call inside Snowflake.
        """
        logger.info("Initializing Nvidia provider request", extra={
            "model_name": self.model_name,
            "temperature": temperature,
            "timeout_seconds": timeout_seconds,
            "structured_output": response_schema is not None,
            "using_langchain": HAS_LANGCHAIN_NVIDIA
        })

        if HAS_LANGCHAIN_NVIDIA:
            return self._generate_langchain(system_instruction, user_prompt, response_schema, temperature, timeout_seconds)
        else:
            return self._generate_requests(system_instruction, user_prompt, response_schema, temperature, timeout_seconds)

    def _generate_langchain(
        self,
        system_instruction: str,
        user_prompt: str,
        response_schema: Optional[Type[BaseModel]],
        temperature: float,
        timeout_seconds: int,
    ) -> Dict[str, Any] | str:
        try:
            kwargs = {
                "model": self.model_name,
                "nvidia_api_key": self.api_key,
                "api_key": self.api_key,
                "temperature": temperature,
                "timeout": float(timeout_seconds),
            }
            if self.base_url and "nvidia.com" not in self.base_url:
                kwargs["base_url"] = self.base_url
            model = ChatNVIDIA(**kwargs)

            start_time = time.perf_counter()

            if response_schema:
                try:
                    structured_model = model.with_structured_output(response_schema)
                    messages = [
                        SystemMessage(content=system_instruction),
                        HumanMessage(content=user_prompt),
                    ]
                    result = structured_model.invoke(messages)
                    latency_ms = int((time.perf_counter() - start_time) * 1000)
                    logger.debug("Structured native response received", extra={"latency_ms": latency_ms})

                    if isinstance(result, BaseModel):
                        return result.model_dump()
                    elif isinstance(result, dict):
                        return result
                    else:
                        raise LLMValidationError(f"Expected structured output, got: {type(result)}")
                except Exception as native_err:
                    logger.warning(
                        "Native structured output failed, falling back to manual JSON formatting",
                        extra={"error": str(native_err)}
                    )
                    schema_json = json.dumps(response_schema.model_json_schema(), indent=2)
                    fallback_system = (
                        f"{system_instruction}\n\n"
                        "You MUST respond ONLY with a raw JSON object matching the JSON schema below. "
                        "Do NOT wrap the response in markdown code blocks. "
                        f"Expected JSON Schema:\n{schema_json}"
                    )
                    raw_res = model.invoke([
                        SystemMessage(content=fallback_system),
                        HumanMessage(content=user_prompt)
                    ])
                    text_content = str(raw_res.content).strip()
                    parsed = self._extract_json(text_content)
                    return response_schema(**parsed).model_dump()
            else:
                raw_res = model.invoke([
                    SystemMessage(content=system_instruction),
                    HumanMessage(content=user_prompt)
                ])
                return str(raw_res.content)
        except Exception as e:
            self._handle_exception(e)

    def _generate_requests(
        self,
        system_instruction: str,
        user_prompt: str,
        response_schema: Optional[Type[BaseModel]],
        temperature: float,
        timeout_seconds: int,
    ) -> Dict[str, Any] | str:
        import requests

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # Format system prompt for JSON schema if required
        active_system = system_instruction
        if response_schema:
            schema_json = json.dumps(response_schema.model_json_schema(), indent=2)
            active_system = (
                f"{system_instruction}\n\n"
                "You MUST respond ONLY with a raw JSON object matching the JSON schema below. "
                "Do NOT wrap the response in markdown code blocks like ```json ... ```. "
                "Do NOT include any explanations, introduction, or trailing text. "
                f"Expected JSON Schema:\n{schema_json}"
            )

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": active_system},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "max_tokens": 1500
        }

        try:
            start_time = time.perf_counter()
            response = requests.post(url, headers=headers, json=payload, timeout=float(timeout_seconds))
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            
            if response.status_code != 200:
                raise LLMProviderError(f"Nvidia API HTTP Error {response.status_code}: {response.text}")
                
            res_data = response.json()
            text_content = res_data["choices"][0]["message"]["content"].strip()
            
            logger.debug("Direct HTTP response received", extra={"latency_ms": latency_ms})

            if response_schema:
                parsed = self._extract_json(text_content)
                validated = response_schema(**parsed)
                return validated.model_dump()
            return text_content
        except Exception as e:
            self._handle_exception(e)

    def _extract_json(self, text: str) -> Dict[str, Any]:
        text_clean = text.strip()
        if text_clean.startswith("```"):
            if text_clean.startswith("```json"):
                text_clean = text_clean[7:]
            else:
                text_clean = text_clean[3:]
            if text_clean.endswith("```"):
                text_clean = text_clean[:-3]
            text_clean = text_clean.strip()
        return json.loads(text_clean)

    def _handle_exception(self, e: Exception):
        if isinstance(e, LLMAnalysisError):
            raise e
        err_msg = str(e).lower()
        logger.error("Nvidia provider call failed", extra={"error": str(e)})

        if "timeout" in err_msg or "timed out" in err_msg or "deadline" in err_msg:
            raise LLMTimeoutError(f"Nvidia API request timed out: {e}")
        elif "rate limit" in err_msg or "429" in err_msg or "quota" in err_msg:
            raise LLMProviderError(f"Nvidia API request rate limited: {e}")
        elif "validation" in err_msg or "pydantic" in err_msg or "jsondecodearray" in err_msg:
            raise LLMValidationError(f"Nvidia response validation failed: {e}")
        else:
            raise LLMProviderError(f"Nvidia API call failed with provider error: {e}")
