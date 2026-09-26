import copy
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional

from config_loader import ConfigError, get_cache_settings
from fetchers.contract_fetcher import fetch_contract_info
from fetchers.etherscan import (ADDRESS_RE, EtherscanError, InvalidInputError,
                                check_chain)
from fetchers.liquidity_fetcher import fetch_liquidity
from fetchers.token_fetcher import ESTIMATE_NOTE, fetch_token_balances
from fetchers.tx_history_fetcher import fetch_tx_history
from schema import AddressContext

logger = logging.getLogger(__name__)

# AddressContext field (fetcher id used in provenance and the cache key, function)
FETCHERS = {
    "contract": ("contract_fetcher", fetch_contract_info),
    "tx_history": ("tx_history_fetcher", fetch_tx_history),
    "tokens": ("token_fetcher", fetch_token_balances),
    "liquidity": ("liquidity_fetcher", fetch_liquidity),
}
NOTES = {"token_fetcher": ESTIMATE_NOTE}

# fetcher_provenance status values
STATUS_OK = "ok"
STATUS_FAILED = "failed"  # the fetcher ran and errored
STATUS_UNAVAILABLE = "unavailable"  # no data source for it yet (stub)

_cache: dict = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_error(error: Exception) -> str:
    # Our own errors are written to be shown, anything else is reduced to its type in case its message carries one.
    if isinstance(error, (EtherscanError, ConfigError)):
        return str(error)
    return type(error).__name__


def _run_cached(chain: str, address: str, fetcher_id: str, fn):
    settings = get_cache_settings()
    key = (chain.lower(), address.lower(), fetcher_id)
    hit = _cache.get(key)
    if settings.enabled and hit and time.monotonic(
    ) - hit[0] < settings.ttl_seconds:
        # fetched_at stays the original fetch time
        return copy.deepcopy(hit[2]), hit[1]

    # A failing fetcher raises here, before anything is cached, so a rate limit or outage is retried on the next message instead of sticking for the TTL.
    value = fn(chain, address)
    fetched_at = _now_iso()
    if settings.enabled:
        _cache[key] = (time.monotonic(), fetched_at, value)
    return copy.deepcopy(value), fetched_at


def clear_cache() -> None:
    _cache.clear()


def build_address_context(
        chain: str,
        address: str,
        fields: Optional[Iterable[str]] = None) -> AddressContext:
    # Checked once here, not per fetcher, so a typo'd address is reported as a typo instead of as four identical fetcher failures.
    if not ADDRESS_RE.match(address):
        raise InvalidInputError(
            f"'{address}' is not a valid address (0x + 40 hex characters)")
    check_chain(chain)

    wanted = FETCHERS.keys() if fields is None else [
        f for f in fields if f in FETCHERS
    ]
    context = {"chain": chain, "address": address, "queried_at": _now_iso()}
    provenance = {}

    for field in wanted:
        fetcher_id, fn = FETCHERS[field]
        # Each fetcher fails on its own: a failure is recorded in provenance and the rest still run, so the agents get whatever partial context there is.
        try:
            value, fetched_at = _run_cached(chain, address, fetcher_id, fn)
        except NotImplementedError:
            logger.info("%s skipped - no data source decided yet", fetcher_id)
            provenance[fetcher_id] = {
                "fields": [field],
                "status": STATUS_UNAVAILABLE,
                "error": "no data source hooked up yet",
            }
            continue
        except Exception as e:
            logger.warning("%s failed: %s", fetcher_id, _safe_error(e))
            provenance[fetcher_id] = {
                "fields": [field],
                "status": STATUS_FAILED,
                "error": _safe_error(e),
            }
            continue

        context[field] = value
        provenance[fetcher_id] = {
            "fields": [field],
            "status": STATUS_OK,
            "fetched_at": fetched_at,
        }
        if fetcher_id in NOTES:
            provenance[fetcher_id]["note"] = NOTES[fetcher_id]

    context["fetcher_provenance"] = provenance
    return AddressContext(**context)


def missing_fields(context: AddressContext) -> Dict[str, str]:
    # Fields a fetcher was asked for but didn't supply, mapped to why (STATUS_FAILED / STATUS_UNAVAILABLE). Their value in the context is only a default ([] / None), so it means "unknown", not "none".
    return {
        field: entry["status"]
        for entry in context.fetcher_provenance.values()
        if entry.get("status", STATUS_OK) != STATUS_OK
        for field in entry.get("fields", [])
    }
