"""Adds a running Detector API Wrapper container as a detector.

The wrapper (see its README, "Docker image setup") serves a small HTTP API:
GET /health, GET /status and POST /call, which answers with an envelope
{"status": ..., "result": <DetectionResult>, "error": ...}. The existing
generic detector connector can already read that, so adding a source only has
to check the container is up and write a detector entry that points at /call.
"""
import json
import re
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests

from config_loader import (ConfigError, load_config, read_added_detectors,
                           save_added_detectors)
from detector.validator import DetectorConfigError, validate_detector_config

ADDED_PREFIX = "wrapper_"
PROBE_TIMEOUT_SECONDS = 5.0
MAX_PROBE_BYTES = 100_000
# The wrapper fetches from the real detector, which can be slow.
CALL_TIMEOUT_SECONDS = 30


class SourceError(ValueError):
    # The message is shown to the user as-is, so it says what to fix.
    pass


def normalise_url(raw: str) -> str:
    text = (raw or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SourceError("Enter the wrapper's address, for example "
                          "http://localhost:8002")
    if parsed.username or parsed.password:
        raise SourceError("Leave the username and password out of the "
                          "address.")
    if parsed.query or parsed.fragment:
        raise SourceError("Enter just the address, without a ? or # part.")
    path = parsed.path.rstrip("/")
    if path.endswith("/call"):
        path = path[:-len("/call")]
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return (slug or "source")[:40]


def build_entry(detector_id: str, name: str, base_url: str) -> Dict[str, Any]:
    return {
        "id": detector_id,
        "name": name,
        "mode": "generic",
        "status": "live",
        "endpoint": base_url + "/call",
        "method": "POST",
        "required_input_type": "address",
        "is_llm_based": False,
        "timeout_seconds": CALL_TIMEOUT_SECONDS,
        "request": {
            "body_template": {
                "resource_id": "{{ address }}",
                "chain": "{{ chain }}"
            }
        },
        "response_mapping": {
            "label": {
                "path": "$.result.label"
            },
            "confidence": {
                "path": "$.result.confidence"
            },
            "risk_type": {
                "path": "$.result.risk_type"
            },
            "evidence": {
                "mode": "list",
                "list_path": "$.result.evidence",
                "item": {
                    "description": "$.description",
                    "weight": "$.weight"
                }
            }
        }
    }


def _probe(base_url: str, path: str) -> Dict[str, Any]:
    url = base_url + path
    try:
        # No redirects: a wrapper that redirects elsewhere is not one we set up.
        response = requests.get(url,
                                timeout=PROBE_TIMEOUT_SECONDS,
                                allow_redirects=False,
                                stream=True)
    except requests.Timeout:
        raise SourceError(f"{base_url} didn't answer within "
                          f"{PROBE_TIMEOUT_SECONDS:g} seconds. Is the "
                          "container running?")
    except requests.RequestException:
        raise SourceError(f"I couldn't reach {base_url}. Is the container "
                          "running, and is the port right?")
    with response:
        if response.status_code != 200:
            raise SourceError(
                f"{base_url}{path} answered HTTP {response.status_code}, so "
                "this doesn't look like the Detector API Wrapper.")
        content = response.raw.read(MAX_PROBE_BYTES + 1, decode_content=True)
    if len(content) > MAX_PROBE_BYTES:
        raise SourceError(f"{base_url}{path} sent back too much data.")
    try:
        data = json.loads(content)
    except ValueError:
        raise SourceError(f"{base_url}{path} didn't answer with JSON, so "
                          "this doesn't look like the Detector API Wrapper.")
    if not isinstance(data, dict):
        raise SourceError(f"{base_url}{path} gave an unexpected answer.")
    return data


def _unique_id(name: str, taken: List[str]) -> str:
    base = ADDED_PREFIX + _slug(name)
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base}_{n}"
        n += 1
    return candidate


def register_wrapper(name: str, url: str) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise SourceError("Give the source a name.")
    base_url = normalise_url(url)

    added = read_added_detectors()
    if any(e.get("endpoint") == base_url + "/call" for e in added):
        raise SourceError("That wrapper has already been added.")
    taken = [d.get("id") for d in load_config().get("detectors", [])]
    entry = build_entry(_unique_id(name, taken), name, base_url)

    # Check the entry before any request goes out, so the https / localhost-only rule applies to the probe too.
    try:
        validate_detector_config({
            k: v
            for k, v in entry.items() if k != "id" and k != "status"
        })
    except DetectorConfigError as e:
        raise SourceError("; ".join(e.errors))

    health = _probe(base_url, "/health")
    if health.get("status") != "ok":
        raise SourceError(f"{base_url} is running but reports that it isn't "
                          "healthy.")
    status = _probe(base_url, "/status")
    if not status.get("detector_configured"):
        raise SourceError(
            "The wrapper is running but has no detector set up. Add your "
            "detector's provider config to the wrapper (see its README) and "
            "restart it.")
    if status.get("required_input_type") not in (None, "address"):
        raise SourceError(
            "This wrapper's detector needs the address's on-chain context, "
            "which adding a source doesn't support yet.")

    try:
        save_added_detectors(added + [entry])
    except OSError:
        raise SourceError("I couldn't save the new source on the server.")
    except ConfigError as e:
        raise SourceError(str(e))
    return entry
