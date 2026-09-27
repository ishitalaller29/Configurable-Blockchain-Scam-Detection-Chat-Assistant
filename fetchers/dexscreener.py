import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests

BASE_URL = "https://api.dexscreener.com"
REQUEST_TIMEOUT = 10
MAX_REQUESTS_PER_MIN = 300
MIN_INTERVAL = 60.0 / MAX_REQUESTS_PER_MIN
MAX_RETRIES = 4
BATCH_LIMIT = 30

LIQUIDITY_CACHE_PATH = os.getenv(
    "DEXSCREENER_CACHE_PATH", "dexscreener_liquidity_cache.json"
)

_throttle_lock = threading.Lock()
_last_request_time = 0.0
_cache_lock = threading.Lock()

def _throttle() -> None:
    global _last_request_time
    with _throttle_lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_request_time)
        if wait > 0:
            time.sleep(wait)
        _last_request_time = time.monotonic()

def _get(path: str, params: Optional[dict] = None) -> Any:
    url = f"{BASE_URL}{path}"
    for attempt in range(MAX_RETRIES):
        _throttle()
        try:
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except requests.RequestException:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == MAX_RETRIES - 1:
                resp.raise_for_status()
            retry_after = resp.headers.get("Retry-After")
            time.sleep(float(retry_after) if retry_after else 2 ** attempt)
            continue

        resp.raise_for_status()
        return resp.json()
    return None

def _as_pair_list(data: Any) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("pairs") or []
    return []

def search_pairs(query: str) -> list[dict]:
    return _as_pair_list(_get("/latest/dex/search", params={"q": query}))


def get_token_pairs(chain_id: str, token_address: str) -> list[dict]:
    """/token-pairs/v1 - every pool a token trades on for one chain."""
    return _as_pair_list(_get(f"/token-pairs/v1/{chain_id}/{token_address}"))

def get_tokens_batch(chain_id: str, token_addresses: list[str]) -> list[dict]:
    results: list[dict] = []
    for i in range(0, len(token_addresses), BATCH_LIMIT):
        chunk = ",".join(token_addresses[i:i + BATCH_LIMIT])
        results.extend(_as_pair_list(_get(f"/tokens/v1/{chain_id}/{chunk}")))
    return results

def get_pair(chain_id: str, pair_address: str) -> Optional[dict]:
    pairs = _as_pair_list(_get(f"/latest/dex/pairs/{chain_id}/{pair_address}"))
    return pairs[0] if pairs else None

def _liquidity_usd(pair: dict) -> float:
    return float((pair.get("liquidity") or {}).get("usd") or 0.0)

def pick_canonical_pair(pairs: list[dict]) -> Optional[dict]:
    return max(pairs, key=_liquidity_usd) if pairs else None

def extract_evidence(pair: dict) -> dict:
    liquidity = pair.get("liquidity") or {}
    txns = pair.get("txns") or {}
    base = pair.get("baseToken") or {}
    created_ms = pair.get("pairCreatedAt")
    age_hours = (
        (time.time() * 1000 - created_ms) / 3_600_000 if created_ms else None
    )

    h24 = txns.get("h24") or {}
    buys_24h, sells_24h = h24.get("buys", 0), h24.get("sells", 0)

    return {
        "chain_id": pair.get("chainId"),
        "dex_id": pair.get("dexId"),
        "pair_address": pair.get("pairAddress"),
        "pair_url": pair.get("url"),
        "token_address": base.get("address"),
        "token_name": base.get("name"),
        "token_symbol": base.get("symbol"),
        "price_usd": pair.get("priceUsd"),
        "liquidity_usd": liquidity.get("usd"),
        "liquidity_base": liquidity.get("base"),
        "liquidity_quote": liquidity.get("quote"),
        "txns": txns,
        "price_change": pair.get("priceChange") or {},
        "fdv": pair.get("fdv"),
        "market_cap": pair.get("marketCap"),
        "pair_created_at": created_ms,
        "pair_age_hours": round(age_hours, 2) if age_hours is not None else None,
        "boosts_active": (pair.get("boosts") or {}).get("active", 0),
        "labels": pair.get("labels") or [],
        "signals": {
            "possible_honeypot": buys_24h > 0 and sells_24h == 0,
            "very_new_pool": age_hours is not None and age_hours < 24,
            "has_paid_boosts": (pair.get("boosts") or {}).get("active", 0) > 0,
        },
    }

def _load_cache() -> dict:
    try:
        with open(LIQUIDITY_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save_cache(cache: dict) -> None:
    tmp = f"{LIQUIDITY_CACHE_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, LIQUIDITY_CACHE_PATH)

def record_and_diff_liquidity(chain_id: str, token_address: str,
                              liquidity_usd: Optional[float]) -> dict:
    return _record_and_diff(
        f"{chain_id}:{(token_address or '').lower()}", liquidity_usd
    )

def _record_and_diff(key: str, liquidity_usd: Optional[float]) -> dict:
    now = int(time.time())
    with _cache_lock:
        cache = _load_cache()
        previous = cache.get(key)
        cache[key] = {"liquidity_usd": liquidity_usd, "timestamp": now}
        _save_cache(cache)
    result = {
        "previous_liquidity_usd": None,
        "previous_timestamp": None,
        "pct_change": None,
    }
    if previous and previous.get("liquidity_usd") and liquidity_usd is not None:
        prev_val = float(previous["liquidity_usd"])
        result.update({
            "previous_liquidity_usd": prev_val,
            "previous_timestamp": previous.get("timestamp"),
            "pct_change": round((liquidity_usd - prev_val) / prev_val * 100, 2),
        })
    return result

def fetch_dexscreener_evidence(query: Optional[str] = None,
                               chain_id: Optional[str] = None,
                               token_address: Optional[str] = None,
                               removal_threshold_pct: float = -50.0) -> dict:
    try:
        if not (chain_id and token_address):
            if not query:
                return {"source": "dexscreener", "found": False,
                        "error": "Provide a query or chain_id + token_address"}
            best = pick_canonical_pair(search_pairs(query))
            if not best:
                return {"source": "dexscreener", "found": False,
                        "error": f"No pairs found for '{query}'"}
            chain_id = best.get("chainId")
            token_address = (best.get("baseToken") or {}).get("address")

        pairs = get_token_pairs(chain_id, token_address)
        canonical = pick_canonical_pair(pairs)
        if not canonical:
            return {"source": "dexscreener", "found": False,
                    "error": f"No pools for {token_address} on {chain_id}"}

        evidence = extract_evidence(canonical)
        diff = record_and_diff_liquidity(
            chain_id, token_address, evidence["liquidity_usd"]
        )
        evidence["liquidity_history"] = diff
        evidence["signals"]["possible_liquidity_removal"] = (
            diff["pct_change"] is not None
            and diff["pct_change"] <= removal_threshold_pct
        )
        evidence["pool_count"] = len(pairs)

        return {"source": "dexscreener", "found": True, **evidence}

    except requests.RequestException as e:
        return {"source": "dexscreener", "found": False,
                "error": f"DexScreener request failed: {e}"}

def _dex_name(pair: dict) -> str:
    dex = pair.get("dexId") or "unknown"
    labels = pair.get("labels") or []
    return f"{dex}_{labels[0]}" if labels else dex

def fetch_liquidity_for_context(chain: str, address: str,
                                max_pools: int = 10,
                                min_event_pct: float = 20.0
                                ) -> tuple[list[dict], dict]:
    now_iso = datetime.now(timezone.utc).isoformat()

    pairs = get_token_pairs(chain, address)
    if not pairs:
        single = get_pair(chain, address)
        pairs = [single] if single else []
    else:
        own = [p for p in pairs
               if ((p.get("baseToken") or {}).get("address") or "").lower()
               == address.lower()]
        pairs = own or pairs

    pairs = sorted(pairs, key=_liquidity_usd, reverse=True)[:max_pools]

    pools: list[dict] = []
    for p in pairs:
        pool_address = p.get("pairAddress") or ""
        liq = _liquidity_usd(p)
        diff = _record_and_diff(f"pool:{chain}:{pool_address.lower()}", liq)

        events: list[dict] = []
        prev = diff["previous_liquidity_usd"]
        if prev and abs(diff["pct_change"] or 0) >= min_event_pct:
            change = liq - prev
            events.append({
                "type": "add" if change > 0 else "remove",
                "timestamp": now_iso,
                "amount_usd": round(abs(change), 2),
            })

        pools.append({
            "pool_address": pool_address,
            "dex": _dex_name(p),
            "token_pair": [
                (p.get("baseToken") or {}).get("symbol") or "UNKNOWN",
                (p.get("quoteToken") or {}).get("symbol") or "UNKNOWN",
            ],
            "liquidity_usd": liq,
            "liquidity_events": events,
        })

    provenance = {
        "liquidity_fetcher": {"fields": ["liquidity"], "fetched_at": now_iso}
    }
    return pools, provenance

if __name__ == "__main__":
    print(json.dumps(fetch_dexscreener_evidence(query="PEPE"), indent=2))
    liquidity, provenance = fetch_liquidity_for_context(
        "ethereum", "0x6982508145454Ce325dDbE47a25d4ec3d2311933"
    )
    print(json.dumps({"liquidity": liquidity,
                      "fetcher_provenance": provenance}, indent=2))