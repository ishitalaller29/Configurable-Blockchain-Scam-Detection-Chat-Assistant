from typing import Any, Dict, List
from urllib.parse import urlparse

from pydantic import ValidationError

from detector.mapping import (ALLOWED_TEMPLATE_TOKENS, find_template_tokens,
                              is_valid_path)
from schema import DetectorConfig

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "host.docker.internal"}


class DetectorConfigError(ValueError):

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _pydantic_errors(error: ValidationError) -> List[str]:
    return [
        f"{'.'.join(str(p) for p in e['loc']) or 'config'}: {e['msg']}"
        for e in error.errors()
    ]


def _check_endpoint(config: DetectorConfig) -> List[str]:
    errors = []
    parsed = urlparse(config.endpoint.replace("{{", "").replace("}}", ""))
    host = (parsed.hostname or "").lower()
    if not host:
        errors.append("endpoint must be an absolute URL")
    elif parsed.scheme != "https" and not (parsed.scheme == "http"
                                           and host in _LOCAL_HOSTS):
        errors.append("endpoint must use https:// (plain http:// is only "
                      "allowed for localhost)")
    for token in find_template_tokens(config.endpoint):
        if token not in ALLOWED_TEMPLATE_TOKENS:
            errors.append(f"endpoint uses unknown token {{{{ {token} }}}}")
    return errors


def _check_paths(config: DetectorConfig) -> List[str]:
    mapping = config.response_mapping
    paths = {"response_mapping.label.path": mapping.label.path}
    for i, override in enumerate(mapping.label.overrides):
        paths[f"response_mapping.label.overrides[{i}].path"] = override.path
    if mapping.risk_type:
        paths["response_mapping.risk_type.path"] = mapping.risk_type.path
    if mapping.confidence:
        paths["response_mapping.confidence.path"] = mapping.confidence.path
    if mapping.explanation:
        paths["response_mapping.explanation.path"] = mapping.explanation.path
    if mapping.evidence:
        paths[
            "response_mapping.evidence.list_path"] = mapping.evidence.list_path
        if mapping.evidence.mode == "list":
            item = mapping.evidence.item
            paths[
                "response_mapping.evidence.item.description"] = item.description
            if item.weight:
                paths["response_mapping.evidence.item.weight"] = item.weight
    return [
        f"{where} {path!r} is not a valid JSON path (e.g. $.result.score)"
        for where, path in paths.items() if not is_valid_path(path)
    ]


def _check_generic(config: DetectorConfig) -> List[str]:
    if config.request is None or config.response_mapping is None:
        return [
            "generic mode needs both 'request' and 'response_mapping' "
            "(body_template may be {})"
        ]
    errors = _check_paths(config)
    for token in find_template_tokens(config.request.body_template):
        if token not in ALLOWED_TEMPLATE_TOKENS:
            errors.append(
                f"request.body_template uses unknown token {{{{ {token} }}}}")
    if config.method == "GET" and config.request.body_template:
        errors.append("a GET request can't carry a body_template")

    mapping = config.response_mapping
    for rule in mapping.label.ranges:
        if all(getattr(rule, k) is None for k in ("gte", "gt", "lte", "lt")):
            errors.append(
                "every label range needs at least one of gte/gt/lte/lt")
    if (mapping.evidence and mapping.evidence.mode == "code_list"
            and not mapping.evidence.codes):
        errors.append("evidence mode 'code_list' needs a 'codes' table")
    if config.is_llm_based and mapping.explanation is None:
        errors.append("an LLM-based detector must map "
                      "response_mapping.explanation to its own text")
    return errors


def validate_detector_config(raw: Dict[str, Any]) -> DetectorConfig:
    if not isinstance(raw, dict):
        raise DetectorConfigError(["the detector config must be an object"])
    try:
        config = DetectorConfig(**raw)
    except ValidationError as e:
        raise DetectorConfigError(_pydantic_errors(e)) from e

    errors = _check_endpoint(config)
    if config.mode == "template":
        if config.request is not None or config.response_mapping is not None:
            errors.append(
                "template mode must not have request / response_mapping")
        if config.method != "POST":
            errors.append("template detectors are called with POST")
    else:
        errors += _check_generic(config)

    if config.auth is not None:
        if "{api_key}" not in config.auth.value_template:
            errors.append("auth.value_template must contain {api_key}")
        if not config.auth.api_key.startswith("env:"):
            errors.append("auth.api_key must be an env:VAR_NAME reference - "
                          "the key itself belongs in .env, not the config")
    if errors:
        raise DetectorConfigError(errors)
    return config
