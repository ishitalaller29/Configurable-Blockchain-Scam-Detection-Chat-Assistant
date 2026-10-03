import json
import os
from pathlib import Path
from typing import Dict

from llm_providers.openai_compatible import OpenAICompatibleProvider

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
FUNCTIONAL_PROVIDERS = ("openai_compatible", )

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


def build_provider_for_agent(agent_key: str,
                              config: Dict[str, dict] = None
                              ) -> OpenAICompatibleProvider:
    """Builds the LLM provider for one agent role from its stored config.

    Every provider value currently resolves to OpenAICompatibleProvider,
    since that is the only adapter implemented so far - openai_native,
    anthropic_native and gemini_native are each a distinct real integration
    (different auth, different request/response shape; Anthropic takes the
    system prompt as a separate field, Gemini uses generateContent with its
    own role names) and are tracked as Sprint 3 follow-up work, not attempted
    here. Selecting one of them is honoured in the stored/displayed config
    (so the UI never lies about what's selected), but functionally this
    still runs the one real adapter underneath.
    """
    config = config or load_agent_config()
    agent_config = config.get(agent_key, _DEFAULT_AGENT_CONFIG)
    # NOTE: when openai_native/anthropic_native/gemini_native adapters exist,
    # branch on agent_config["provider"] here and construct the matching one.
    return OpenAICompatibleProvider(
        base_url=agent_config.get("base_url") or LLM_CONFIG["base_url"],
        api_key=agent_config.get("api_key") or LLM_CONFIG["api_key"],
        model=agent_config.get("model") or LLM_CONFIG["model"],
    )


def build_default_provider() -> OpenAICompatibleProvider:
    # Kept for any other caller (e.g. cli.py) that still wants one shared
    # provider built from the original hardcoded LLM_CONFIG.
    return OpenAICompatibleProvider(
        base_url=LLM_CONFIG["base_url"],
        api_key=LLM_CONFIG["api_key"],
        model=LLM_CONFIG["model"],
    )