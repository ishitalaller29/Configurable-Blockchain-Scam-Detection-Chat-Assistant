import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests
from pydantic import ValidationError

from config_loader import ConfigError, resolve_secret
from detector.mapping import (MappingError, build_request, map_explanation,
                              map_response)
from fetchers.etherscan import ADDRESS_RE
from schema import (AddressContext, DetectionResult, DetectionResultCore,
                    DetectorConfig)

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
MAX_RESPONSE_BYTES = 1_000_000

ERROR_CONFIG = "config"
ERROR_UNREACHABLE = "unreachable"
ERROR_REJECTED = "rejected"
ERROR_UNREADABLE = "unreadable"

_CORE_FIELDS = ("label", "risk_type", "confidence", "evidence")


@dataclass
class DetectorOutcome:
    ok: bool
    detector_name: str
    core: Optional[DetectionResultCore] = None
    explanation: Optional[str] = None
    error_kind: Optional[str] = None
    error: Optional[str] = None
    notes: List[str] = field(default_factory=list)


def _fail(config: DetectorConfig,
          kind: str,
          message: str,
          notes: Optional[List[str]] = None) -> DetectorOutcome:
    logger.warning("detector %s failed (%s)", config.name, kind)
    return DetectorOutcome(ok=False,
                           detector_name=config.name,
                           error_kind=kind,
                           error=message,
                           notes=notes or [])


def _auth_headers(config: DetectorConfig) -> Dict[str, str]:
    if config.auth is None:
        return {}
    secret = resolve_secret(config.auth.api_key)
    return {
        config.auth.header_name:
        config.auth.value_template.replace("{api_key}", secret)
    }


def _build(config: DetectorConfig, address: str, chain: str,
           context: Optional[AddressContext]) -> Dict[str, Any]:
    if config.mode == "generic":
        return build_request(config, {"address": address, "chain": chain})
    if config.required_input_type == "address_with_context":
        if context is None:
            raise MappingError(
                "this detector needs the address's on-chain context, but "
                "none was fetched")
        body = context.model_dump(by_alias=True)
    else:
        body = {"address": address, "chain": chain}
    return {
        "url": config.endpoint,
        "method": "POST",
        "body": body,
        "query": {}
    }


def _send(config: DetectorConfig, request: Dict[str, Any],
          headers: Dict[str, str]) -> requests.Response:
    for attempt in range(MAX_ATTEMPTS):
        last_try = attempt == MAX_ATTEMPTS - 1
        try:
            response = requests.request(request["method"],
                                        request["url"],
                                        headers=headers,
                                        params=request["query"] or None,
                                        json=request["body"],
                                        timeout=config.timeout_seconds,
                                        stream=True)
        except (requests.Timeout, requests.ConnectionError):
            if last_try:
                raise
            continue
        if response.status_code >= 500 and not last_try:
            response.close()
            continue
        return response


def _read_json(response: requests.Response) -> Any:
    content = response.raw.read(MAX_RESPONSE_BYTES + 1, decode_content=True)
    if len(content) > MAX_RESPONSE_BYTES:
        raise ValueError("reply is too large")
    return json.loads(content)


def _delay_notes(config: DetectorConfig,
                 response: requests.Response) -> List[str]:
    delay = response.headers.get("X-Data-Delay-Seconds", "").strip()
    try:
        minutes = int(float(delay)) // 60
    except ValueError:
        return []
    if minutes <= 0:
        return []
    return [
        f"{config.name}'s data can be about {minutes} minutes behind, so "
        "very recent activity may not be reflected yet."
    ]


def _read_template_reply(config: DetectorConfig, raw: Any) -> DetectorOutcome:
    if not isinstance(raw, dict):
        raise ValueError("the reply is not a JSON object")
    core = DetectionResultCore(**{k: raw[k] for k in _CORE_FIELDS if k in raw})
    explanation = None
    if config.is_llm_based:
        explanation = DetectionResult(**raw).explanation
    return DetectorOutcome(ok=True,
                           detector_name=config.name,
                           core=core,
                           explanation=explanation)


def run_detector(config: DetectorConfig,
                 address: str,
                 chain: str,
                 context: Optional[AddressContext] = None) -> DetectorOutcome:
    name = config.name
    if not ADDRESS_RE.match(address or ""):
        return _fail(
            config, ERROR_CONFIG,
            f"'{address}' isn't a valid address (0x + 40 hex characters), "
            f"so I didn't send it to {name}.")

    try:
        headers = {"Accept": "application/json", **_auth_headers(config)}
        request = _build(config, address, chain, context)
    except ConfigError as e:
        return _fail(config, ERROR_CONFIG, f"{name} isn't set up right: {e}.")
    except MappingError as e:
        return _fail(config, ERROR_CONFIG,
                     f"{name}'s request couldn't be built: {e}.")

    logger.info("calling detector %s: %s %s", name, request["method"],
                request["url"])
    try:
        response = _send(config, request, headers)
    except requests.Timeout:
        return _fail(
            config, ERROR_UNREACHABLE,
            f"{name} didn't answer within {config.timeout_seconds:g} seconds.")
    except requests.RequestException:
        return _fail(config, ERROR_UNREACHABLE, f"I couldn't reach {name}.")

    with response:
        notes = _delay_notes(config, response)
        status = response.status_code
        if status >= 500:
            return _fail(config, ERROR_UNREACHABLE,
                         f"{name} is unavailable right now (HTTP {status}).",
                         notes)
        if status >= 400:
            message = f"{name} rejected the request (HTTP {status})"
            if status in (401, 403):
                message += " - it looks like its API key is missing or wrong"
            elif status == 429:
                message += " - it's rate limiting us"
            return _fail(config, ERROR_REJECTED, message + ".", notes)
        try:
            raw = _read_json(response)
        except ValueError:
            return _fail(config, ERROR_UNREADABLE,
                         f"{name} replied, but not with JSON I could read.",
                         notes)

    try:
        if config.mode == "template":
            outcome = _read_template_reply(config, raw)
        else:
            outcome = DetectorOutcome(
                ok=True,
                detector_name=name,
                core=map_response(config.response_mapping, raw),
                explanation=(map_explanation(config.response_mapping, raw)
                             if config.is_llm_based else None))
    except (MappingError, ValidationError, ValueError) as e:
        logger.warning("detector %s reply unreadable: %s", name,
                       type(e).__name__)
        return _fail(
            config, ERROR_UNREADABLE,
            f"{name} replied, but its answer couldn't be read "
            f"({_short(e)}).", notes)

    if config.is_llm_based and not outcome.explanation:
        return _fail(
            config, ERROR_UNREADABLE,
            f"{name} is set up as LLM-based, but its reply had no "
            "explanation text.", notes)
    outcome.notes = notes
    return outcome


def _short(error: Exception) -> str:
    return str(error).splitlines()[0][:200]
