"""
POV-4: LLM Providers module.
"""

import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="google.generativeai")
warnings.filterwarnings("ignore", category=FutureWarning, module="langchain_google_genai")


from src.agents.providers.base import (
    LLMProvider,
    LLMAnalysisError,
    LLMProviderError,
    LLMTimeoutError,
    LLMValidationError,
)
from src.agents.providers.gemini import GeminiProvider
from src.agents.providers.nvidia import NvidiaProvider
from src.core.config import Settings


def get_provider(settings: Settings) -> LLMProvider:
    """
    Factory function to instantiate the active LLMProvider based on configuration.
    """
    provider_name = settings.llm.provider.lower()
    if provider_name == "gemini":
        api_key = settings.llm.api_key or settings.gemini.api_key
        model = settings.llm.model or settings.gemini.model_name
        return GeminiProvider(api_key=api_key, model_name=model)
    elif provider_name == "nvidia":
        api_key = settings.llm.api_key
        model = settings.llm.model or "meta/llama-3.1-8b-instruct"
        base_url = settings.llm.base_url
        return NvidiaProvider(api_key=api_key, model_name=model, base_url=base_url)
    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")
