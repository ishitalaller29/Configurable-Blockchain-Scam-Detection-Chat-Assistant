from typing import Dict
import json
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

# Per-agent LLM backend config (FR-14). Persisted to a JSON file so admin
# changes survive a server restart, per spec 7 ("local SQLite or JSON file
# for connector/backend configs - no need for a full database design").
AGENT_KEYS = ("business_analyser", "scam_checker", "forensic_investigator")

# Only openai_compatible has a real adapter built right now. The other three
# provider types are selectable and persisted so the admin UI can be built
# and tested end-to-end, but selecting one of them currently still runs on
# the openai_compatible adapter underneath (see build_provider_for_agent) -
# this is a known, intentional gap, flagged for Sprint 3 adapter work rather
# than attempted here.
SUPPORTED_PROVIDERS = (
    "openai_native",
    "anthropic_native",
    "gemini_native",
    "openai_compatible",
)
FUNCTIONAL_PROVIDERS = SUPPORTED_PROVIDERS

NATIVE_PROVIDERS = {
    "openai": ("llm_providers.openai_native", "OpenAINativeProvider",
               "OPENAI_API_KEY"),
    "gemini": ("llm_providers.gemini_native", "GeminiNativeProvider",
               "GEMINI_API_KEY"),
    "anthropic": ("llm_providers.anthropic_native", "AnthropicNativeProvider",
                  "ANTHROPIC_API_KEY"),
}

_CONFIG_PATH = Path(__file__).resolve().parent / "llm_config.json"

_DEFAULT_AGENT_CONFIG = dict(
    provider="openai_compatible",
    base_url=LLM_CONFIG["base_url"],
    api_key=LLM_CONFIG["api_key"],
    model=LLM_CONFIG["model"],
)


def _default_config() -> Dict[str, dict]:
    return {key: dict(_DEFAULT_AGENT_CONFIG) for key in AGENT_KEYS}


def load_agent_config() -> Dict[str, dict]:
    """Reads the per-agent LLM backend config from disk, creating it with
    today's hardcoded defaults the first time this runs."""
    if not _CONFIG_PATH.exists():
        save_agent_config(_default_config())
    with open(_CONFIG_PATH, "r") as f:
        data = json.load(f)
    # Backfill any agent key missing from an older/partial file on disk,
    # rather than failing - config this task writes should never be able to
    # leave the app unable to start.
    for key in AGENT_KEYS:
        data.setdefault(key, dict(_DEFAULT_AGENT_CONFIG))
    return data


def save_agent_config(config: Dict[str, dict]) -> None:
    with open(_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

def _build_native(name: str, api_key: str, model: str) -> LLMProvider:
    module_name, class_name, key_var = NATIVE_PROVIDERS[name]
    api_key = api_key or os.getenv(key_var)
    if not api_key:
        raise ValueError(f"No API key for {name}: set it in the config "
                         f"or add {key_var} to .env")
    if not model:
        raise ValueError(f"No model set for {name}")
    provider_class = getattr(importlib.import_module(module_name), class_name)
    return provider_class(api_key=api_key, model=model)


def build_provider_for_agent(agent_key: str,
                             config: Dict[str, dict] = None) -> LLMProvider:
    config = config or load_agent_config()
    agent_config = config.get(agent_key, _DEFAULT_AGENT_CONFIG)
    provider = agent_config.get("provider", "openai_compatible")
    name = provider.removesuffix("_native")  # "openai_native" -> "openai"

    if name in NATIVE_PROVIDERS:
        return _build_native(name,
                             agent_config.get("api_key"),
                             agent_config.get("model"))
    return OpenAICompatibleProvider(
        base_url=agent_config.get("base_url") or LLM_CONFIG["base_url"],
        api_key=agent_config.get("api_key") or LLM_CONFIG["api_key"],
        model=agent_config.get("model") or LLM_CONFIG["model"],
    )


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
    return _build_native(name, None, os.getenv("LLM_MODEL"))