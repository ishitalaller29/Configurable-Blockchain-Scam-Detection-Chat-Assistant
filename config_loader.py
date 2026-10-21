import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import List, Literal, Optional, Tuple

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

from detector.validator import DetectorConfigError, validate_detector_config
from schema import DetectorConfig

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config" / "app_config.json"
# Detectors a user adds from the chat page ("+ add source"). Kept out of app_config.json so the committed config stays the same on every machine; this file is local and not committed.
ADDED_SOURCES_PATH = PROJECT_ROOT / "config" / "added_sources.json"
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


def read_added_detectors(path: Path = ADDED_SOURCES_PATH) -> List[dict]:
    # A missing or unreadable file means no added sources: a bad local file must not stop the app from starting.
    try:
        data = json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    entries = data.get("detectors") if isinstance(data, dict) else None
    return [e for e in entries if isinstance(e, dict)
            ] if isinstance(entries, list) else []


def save_added_detectors(entries: List[dict],
                         path: Path = ADDED_SOURCES_PATH) -> None:
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"detectors": entries}, indent=2))
    tmp.replace(path)
    load_config.cache_clear()


@lru_cache(maxsize=None)
def load_config(path: Path = CONFIG_PATH) -> dict:
    try:
        raw = json.loads(Path(path).read_text())
    except FileNotFoundError as e:
        raise ConfigError(f"Config file not found: {path}") from e
    except json.JSONDecodeError as e:
        raise ConfigError(
            f"Config file is not valid JSON: {path} ({e})") from e
    config = _strip_comments(raw)
    if Path(path) == CONFIG_PATH:
        known = {d.get("id") for d in config.get("detectors", [])}
        config["detectors"] = list(config.get("detectors", [])) + [
            d for d in read_added_detectors() if d.get("id") not in known
        ]
    return config


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


_ACTIVE_DETECTOR_LINE = re.compile(r'^(\s*"active_detector":\s*)[^,\n]*', re.M)


def set_active_detector(detector_id: Optional[str],
                        path: Path = CONFIG_PATH) -> None:
    # None means no detector, so scam_check falls back to the Scam Checker.
    if detector_id is not None:
        get_detector(detector_id, path)
    text = Path(path).read_text()
    new_text, count = _ACTIVE_DETECTOR_LINE.subn(
        lambda m: m.group(1) + json.dumps(detector_id), text, count=1)
    if count == 0:
        raise ConfigError(f"No active_detector key in {path}")
    Path(path).write_text(new_text)
    load_config.cache_clear()


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
