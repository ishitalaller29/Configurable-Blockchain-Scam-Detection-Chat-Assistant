import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from schema import (LABEL_VALUES, DetectionResultCore, DetectorConfig,
                    Evidence, ResponseMapping)


class MappingError(ValueError):
    pass


_MISSING = object()
_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_PATH_RE = re.compile(r"^\$(?:\.[A-Za-z_][A-Za-z0-9_\-]*|\[\d+\])*$")
_STEP_RE = re.compile(r"\.([A-Za-z_][A-Za-z0-9_\-]*)|\[(\d+)\]")

ALLOWED_TEMPLATE_TOKENS = ("address", "chain")


def is_valid_path(path: str) -> bool:
    return bool(path) and bool(_PATH_RE.match(path))


def get_path(data: Any, path: str, default: Any = _MISSING) -> Any:
    if not is_valid_path(path):
        raise MappingError(f"invalid JSON path {path!r}")
    current = data
    for key, index in _STEP_RE.findall(path[1:]):
        if key:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        else:
            i = int(index)
            if not isinstance(current, list) or i >= len(current):
                return default
            current = current[i]
    return current


def find_template_tokens(value: Any) -> List[str]:
    if isinstance(value, str):
        return _TOKEN_RE.findall(value)
    if isinstance(value, dict):
        return [t for v in value.values() for t in find_template_tokens(v)]
    if isinstance(value, list):
        return [t for v in value for t in find_template_tokens(v)]
    return []


def _fill(value: Any, variables: Dict[str, str]) -> Any:
    if isinstance(value, str):

        def replace(match):
            name = match.group(1)
            if name not in variables:
                raise MappingError(f"unknown template token {{{{ {name} }}}}")
            return variables[name]

        return _TOKEN_RE.sub(replace, value)
    if isinstance(value, dict):
        return {k: _fill(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, variables) for v in value]
    return value


def build_request(config: DetectorConfig,
                  resolved_input: Dict[str, str]) -> Dict[str, Any]:
    variables = {
        "address": str(resolved_input.get("address") or ""),
        "chain": str(resolved_input.get("chain") or "ethereum"),
    }
    if not variables["address"]:
        raise MappingError("there is no address to send to the detector")
    url = _fill(config.endpoint, variables)
    body = None
    if config.method == "POST":
        template = config.request.body_template if config.request else {}
        body = _fill(template, variables)
    return {"url": url, "method": config.method, "body": body, "query": {}}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _to_number(value: Any, what: str) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            pass
    raise MappingError(f"{what} is present but not a number: {value!r}")


def _in_range(number: float, rule) -> bool:
    return ((rule.gte is None or number >= rule.gte)
            and (rule.gt is None or number > rule.gt)
            and (rule.lte is None or number <= rule.lte)
            and (rule.lt is None or number < rule.lt))


def _override_matches(override, raw_json: Any) -> bool:
    found = get_path(raw_json, override.path)
    if found is _MISSING:
        return False
    if override.min_items is not None or override.max_items is not None:
        if not isinstance(found, list):
            return False
        return (
            (override.min_items is None or len(found) >= override.min_items)
            and
            (override.max_items is None or len(found) <= override.max_items))
    if override.contains is not None:
        if not isinstance(found, list):
            return False
        wanted = {code.lower() for code in override.contains}
        return any(str(item).lower() in wanted for item in found)
    if isinstance(override.equals, bool) or isinstance(found, bool):
        return found is override.equals
    if isinstance(override.equals, str) and isinstance(found, str):
        return found.lower() == override.equals.lower()
    return found == override.equals


def _map_label(mapping, raw_json: Any) -> Tuple[str, bool]:
    """Returns (label, overridden)."""
    raw = get_path(raw_json, mapping.path)
    if raw is _MISSING or raw is None:
        raise MappingError(
            f"the reply has no label at {mapping.path}, which is required")

    for override in mapping.overrides:
        if _override_matches(override, raw_json):
            return override.value, True
    return _label_from_value(mapping, raw), False


def _label_from_value(mapping, raw: Any) -> str:
    if mapping.value and mapping.value.map:
        for code, label in mapping.value.map.items():
            if code.lower() == str(raw).lower():
                return label

    if mapping.ranges and not isinstance(raw, bool):
        try:
            number = _to_number(raw, "label")
        except MappingError:
            number = None
        if number is not None:
            for rule in mapping.ranges:
                if _in_range(number, rule):
                    return rule.value

    if isinstance(raw, str) and raw.lower() in LABEL_VALUES:
        return raw.lower()
    return mapping.fallback


def _map_confidence(mapping, raw_json: Any, label: str,
                    overridden: bool) -> float:
    if mapping is None:
        return 0.0
    raw = get_path(raw_json, mapping.path)
    if raw is _MISSING or raw is None:
        return _clamp01(mapping.default)
    number = _clamp01(
        _to_number(raw, f"confidence at {mapping.path}") / mapping.scale)
    if overridden:
        return _clamp01(mapping.default)
    if mapping.measures == "label":
        return number
    risk = 1.0 - number if mapping.measures == "safety" else number
    if label == "scam":
        return risk
    if label == "not_scam":
        return 1.0 - risk
    return _clamp01(mapping.default)


def _map_risk_type(mapping, raw_json: Any) -> Optional[str]:
    if mapping is None:
        return None
    raw = get_path(raw_json, mapping.path)
    if raw is _MISSING or raw is None:
        return None
    text = str(raw).strip()
    return text[:mapping.max_length] or None


def _map_evidence(mapping, raw_json: Any) -> List[Evidence]:
    if mapping is None:
        return []
    items = get_path(raw_json, mapping.list_path)
    if items is _MISSING or items is None:
        return []
    if not isinstance(items, list):
        raise MappingError(f"evidence at {mapping.list_path} is not a list")

    evidence = []
    if mapping.mode == "code_list":
        codes = {k.lower(): v for k, v in mapping.codes.items()}
        for code in items:
            if mapping.code_path:
                code = get_path(code, mapping.code_path, None)
            if code is None:
                continue
            entry = codes.get(str(code).lower())
            if entry is None:
                evidence.append(
                    Evidence(description=str(code),
                             weight=mapping.default_weight))
            else:
                evidence.append(
                    Evidence(description=entry.description,
                             weight=entry.weight))
        return evidence

    for item in items:
        description = get_path(item, mapping.item.description, None)
        if description is None or not str(description).strip():
            continue
        description = str(description).strip()
        if mapping.item.title:
            title = get_path(item, mapping.item.title, None)
            if title is not None and str(title).strip():
                description = f"{str(title).strip()}: {description}"
        evidence.append(
            Evidence(description=description,
                     weight=_clamp01(_item_weight(mapping, item))))
    return evidence


def _item_weight(mapping, item: Any) -> float:
    if not mapping.item.weight:
        return mapping.default_weight
    raw_weight = get_path(item, mapping.item.weight, None)
    if raw_weight is None:
        return mapping.default_weight
    if isinstance(raw_weight, str) and mapping.item.weight_map:
        words = {k.lower(): v for k, v in mapping.item.weight_map.items()}
        if raw_weight.strip().lower() in words:
            return words[raw_weight.strip().lower()]
    try:
        return _to_number(raw_weight, "evidence weight")
    except MappingError:
        return mapping.default_weight


def map_response(response_mapping: ResponseMapping,
                 raw_json: Any) -> DetectionResultCore:
    if not isinstance(raw_json, (dict, list)):
        raise MappingError("the reply is not a JSON object")
    label, overridden = _map_label(response_mapping.label, raw_json)
    try:
        return DetectionResultCore(
            label=label,
            risk_type=_map_risk_type(response_mapping.risk_type, raw_json),
            confidence=_map_confidence(response_mapping.confidence, raw_json,
                                       label, overridden),
            evidence=_map_evidence(response_mapping.evidence, raw_json),
        )
    except ValidationError as e:
        raise MappingError(f"the mapped result is invalid: {e}") from e


def map_explanation(response_mapping: ResponseMapping,
                    raw_json: Any) -> Optional[str]:
    if response_mapping.explanation is None:
        return None
    raw = get_path(raw_json, response_mapping.explanation.path, None)
    if raw is None or not str(raw).strip():
        return None
    return str(raw).strip()
