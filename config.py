import importlib
import os
from pathlib import Path

from dotenv import load_dotenv

from llm_providers.base import LLMProvider
from llm_providers.openai_compatible import OpenAICompatibleProvider

load_dotenv(Path(__file__).resolve().parent / ".env")

LLM_CONFIG = dict(
    base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    api_key="not-needed",
    model=os.getenv("OLLAMA_MODEL", "llama3.1"),
    temperature=0.0,
    max_tokens=800,
)

NATIVE_PROVIDERS = {
    "openai": ("llm_providers.openai_native", "OpenAINativeProvider",
               "OPENAI_API_KEY"),
    "gemini": ("llm_providers.gemini_native", "GeminiNativeProvider",
               "GEMINI_API_KEY"),
    "anthropic": ("llm_providers.anthropic_native", "AnthropicNativeProvider",
                  "ANTHROPIC_API_KEY"),
}

def build_default_provider() -> LLMProvider:
    name = os.getenv("LLM_PROVIDER", "openai_compatible").strip().lower()

    if name == "openai_compatible":
        return OpenAICompatibleProvider(
            base_url=LLM_CONFIG["base_url"],
            api_key=LLM_CONFIG["api_key"],
            model=LLM_CONFIG["model"],
        )
    if name not in NATIVE_PROVIDERS:
        known = ", ".join(["openai_compatible", *NATIVE_PROVIDERS])
        raise ValueError(f"Unknown LLM_PROVIDER '{name}' (known: {known})")
    module_name, class_name, key_var = NATIVE_PROVIDERS[name]
    api_key = os.getenv(key_var)
    model = os.getenv("LLM_MODEL")
    if not api_key:
        raise ValueError(f"{key_var} is not set - add it to .env")
    if not model:
        raise ValueError(
            f"LLM_MODEL is not set - add the {name} model name to .env")
    provider_class = getattr(importlib.import_module(module_name), class_name)
    return provider_class(api_key=api_key, model=model)