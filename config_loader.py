import json
import os
from functools import lru_cache
from pathlib import Path
from typing import List, Literal, Optional, Tuple

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

from detector.validator import DetectorConfigError, validate_detector_config
from schema import DetectorConfig

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config" / "app_config.json"
_STORE_ONLY_KEYS = ("id", "status", "extends")

# Real environment variables win over .env, so Docker/CI can override it.
load_dotenv(PROJECT_ROOT / ".env")


class ConfigError(Exception):
    pass


class RateLimit(BaseModel):
    calls_per_second: int = Field(gt=0)
    calls_per_day: int = Field(gt=0)


class DataSource(BaseModel):
    id: str
    status: Literal["stub", "planned", "blocked", "live"]
    base_url: Optional[str] = None
    chain_id: Optional[int] = None
    api_key: Optional[str] = None
    rate_limit: Optional[RateLimit] = None
    backs: List[str] = Field(default_factory=list)


class CacheSettings(BaseModel):
    enabled: bool
    ttl_seconds: int = Field(gt=0)
    key: List[str]


def _strip_comments(node):
    if isinstance(node, dict):
        return {
            k: _strip_comments(v)
            for k, v in node.items() if not k.startswith("//")
        }
    if isinstance(node, list):
        return [_strip_comments(item) for item in node]
    return node


@lru_cache(maxsize=None)
def load_config(path: Path = CONFIG_PATH) -> dict:
    try:
        raw = json.loads(Path(path).read_text())
    except FileNotFoundError as e:
        raise ConfigError(f"Config file not found: {path}") from e
    except json.JSONDecodeError as e:
        raise ConfigError(
            f"Config file is not valid JSON: {path} ({e})") from e
    return _strip_comments(raw)


def get_data_source(source_id: str, path: Path = CONFIG_PATH) -> DataSource:
    entries = load_config(path).get("data_sources", [])
    entry = next((e for e in entries if e.get("id") == source_id), None)
    if entry is None:
        known = ", ".join(e.get("id", "?") for e in entries) or "none"
        raise ConfigError(
            f"No data source '{source_id}' in config (known: {known})")

    try:
        source = DataSource(**entry)
    except ValidationError as e:
        raise ConfigError(
            f"Data source '{source_id}' is malformed: {e}") from e

    if source.status == "blocked":
        raise ConfigError(
            f"Data source '{source_id}' is blocked - no endpoint decided yet")
    if not source.base_url:
        raise ConfigError(f"Data source '{source_id}' has no base_url")
    return source


def get_cache_settings(path: Path = CONFIG_PATH) -> CacheSettings:
    block = load_config(path).get("cache")
    if block is None:
        raise ConfigError("Config has no 'cache' block")
    try:
        return CacheSettings(**block)
    except ValidationError as e:
        raise ConfigError(f"Cache settings are malformed: {e}") from e


def _detector_entry(detector_id: str, entries: List[dict]) -> dict:
    entry = next((e for e in entries if e.get("id") == detector_id), None)
    if entry is None:
        known = ", ".join(e.get("id", "?") for e in entries) or "none"
        raise ConfigError(
            f"Detector '{detector_id}' is not in config (known: {known})")
    base_id = entry.get("extends")
    if not base_id:
        return entry
    base = next((e for e in entries if e.get("id") == base_id), None)
    if base is None:
        raise ConfigError(
            f"Detector '{detector_id}' extends '{base_id}', which is not in "
            "config")
    if base.get("extends"):
        raise ConfigError(
            f"Detector '{detector_id}' extends '{base_id}', which itself "
            "extends another detector - only one level is allowed")
    return {**base, **entry}


def get_detector(detector_id: str, path: Path = CONFIG_PATH) -> DetectorConfig:
    entry = _detector_entry(detector_id,
                            load_config(path).get("detectors", []))
    mapping_file = {
        k: v
        for k, v in entry.items() if k not in _STORE_ONLY_KEYS
    }
    try:
        return validate_detector_config(mapping_file)
    except DetectorConfigError as e:
        raise ConfigError(
            f"Detector '{detector_id}' config is invalid: {e}") from e


def list_detectors(path: Path = CONFIG_PATH) -> List[dict]:
    entries = load_config(path).get("detectors", [])
    choices = []
    for raw in entries:
        entry = _detector_entry(raw.get("id", ""), entries)
        choices.append({
            "id": entry.get("id"),
            "name": entry.get("name"),
            "status": entry.get("status"),
            "mode": entry.get("mode"),
            "is_llm_based": bool(entry.get("is_llm_based")),
        })
    return choices


def get_active_detector(
        path: Path = CONFIG_PATH) -> Optional[Tuple[str, DetectorConfig]]:
    config = load_config(path)
    detector_id = os.environ.get("ACTIVE_DETECTOR",
                                 config.get("active_detector") or "")
    if not detector_id or detector_id.lower() in ("none", "null"):
        return None
    return detector_id, get_detector(detector_id, path)


def resolve_secret(value: Optional[str]) -> str:
    if not value:
        raise ConfigError("No secret configured")
    if not value.startswith("env:"):
        return value

    var_name = value[len("env:"):]
    secret = os.environ.get(var_name)
    if not secret:
        raise ConfigError(
            f"{var_name} is not set - add it to .env in the project root")
    return secret
