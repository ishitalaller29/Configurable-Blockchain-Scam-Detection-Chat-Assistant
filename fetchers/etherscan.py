import re
import threading
import time
from datetime import datetime, timezone

import requests

from config_loader import get_data_source, resolve_secret

SOURCE_ID = "etherscan"
SUPPORTED_CHAIN = "ethereum"
TIMEOUT_SECONDS = 10
MAX_ATTEMPTS = 3
RATE_LIMIT_MARKER = "rate limit"

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
TX_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
NOTHING_FOUND_RE = re.compile(r"^No .* found", re.IGNORECASE)

_session = requests.Session()
_throttle_lock = threading.Lock()
_last_call_at = 0.0
_daily_calls = {"day": None, "count": 0}


class EtherscanError(Exception):
    pass


class InvalidInputError(EtherscanError):
    # The address or tx hash is malformed, a user typo, not an Etherscan problem.
    pass


class UnsupportedChainError(EtherscanError):
    # The user asked about a chain we can't look up, so this is answered with a question, not reported as an outage.
    pass


def check_chain(chain: str) -> None:
    if chain.lower() != SUPPORTED_CHAIN:
        raise UnsupportedChainError(
            f"chain '{chain}' is not supported - only {SUPPORTED_CHAIN}")


def _validate(params: dict) -> None:
    # Etherscan answers a malformed address like "0x123" with "No transactions found", which is indistinguishable from a real empty wallet
    for key in ("address", "contractaddress"):
        if key in params and not ADDRESS_RE.match(str(params[key])):
            raise InvalidInputError(
                f"'{params[key]}' is not a valid address (0x + 40 hex characters)"
            )
    if "contractaddresses" in params:
        for addr in str(params["contractaddresses"]).split(","):
            if not ADDRESS_RE.match(addr.strip()):
                raise InvalidInputError(
                    f"'{addr}' is not a valid address (0x + 40 hex characters)"
                )
    if "txhash" in params and not TX_HASH_RE.match(str(params["txhash"])):
        raise InvalidInputError(
            f"'{params['txhash']}' is not a valid tx hash (0x + 64 hex characters)"
        )


def _count_daily_call(calls_per_day: int) -> None:
    # Process-local count, reset at UTC midnight
    today = datetime.now(timezone.utc).date()
    with _throttle_lock:
        if _daily_calls["day"] != today:
            _daily_calls["day"], _daily_calls["count"] = today, 0
        if _daily_calls["count"] >= calls_per_day:
            raise EtherscanError(
                f"daily limit of {calls_per_day} calls reached")
        _daily_calls["count"] += 1


def _throttle(calls_per_second: int) -> None:
    # Spaces calls out so a burst of fetchers stays under the free-tier cap.
    global _last_call_at
    min_interval = 1.0 / calls_per_second
    with _throttle_lock:
        wait = _last_call_at + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()


def _unwrap(module: str, data: dict):
    # status/message check. Auth and rate-limit failures come back as status "0" on every module, proxy included, so this runs first.
    if data.get("status") == "0":
        message = data.get("message") or ""
        result = data.get("result")
        if NOTHING_FOUND_RE.match(message):
            return result if isinstance(result, list) else []
        raise EtherscanError(result if isinstance(result, str) and result else
                             message or "unknown error")

    if module == "proxy":
        # JSON-RPC shape: no status/message, success is result-vs-error presence.
        if "error" in data:
            error = data["error"]
            raise EtherscanError(
                error.get("message", error) if isinstance(error, dict
                                                          ) else error)
        if "result" not in data:
            raise EtherscanError("proxy response has neither result nor error")
        return data["result"]

    if "result" not in data:
        raise EtherscanError(data.get("message", "unexpected response shape"))
    return data["result"]


def etherscan_request(module: str, action: str, **params):
    # Shared entry point for every Etherscan v2 call.

    _validate(params)
    source = get_data_source(SOURCE_ID)
    api_key = resolve_secret(
        source.api_key)  # fails fast if ETHERSCAN_API_KEY is missing
    calls_per_second = source.rate_limit.calls_per_second if source.rate_limit else 5
    calls_per_day = source.rate_limit.calls_per_day if source.rate_limit else 100_000

    query = {
        "chainid": source.chain_id,
        "module": module,
        "action": action,
        **params,
        "apikey": api_key,
    }

    for attempt in range(1, MAX_ATTEMPTS + 1):
        _count_daily_call(calls_per_day)
        _throttle(calls_per_second)
        try:
            resp = _session.get(source.base_url,
                                params=query,
                                timeout=TIMEOUT_SECONDS)
            resp.raise_for_status()
            data = resp.json()
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt == MAX_ATTEMPTS:
                raise EtherscanError(
                    f"{module}/{action}: network error ({type(e).__name__})"
                ) from None
        except requests.HTTPError:
            if resp.status_code < 500 or attempt == MAX_ATTEMPTS:
                raise EtherscanError(
                    f"{module}/{action}: HTTP {resp.status_code}") from None
        except ValueError as e:
            raise EtherscanError(
                f"{module}/{action}: response is not JSON") from e
        except requests.RequestException as e:
            raise EtherscanError(
                f"{module}/{action}: request failed ({type(e).__name__})"
            ) from None
        else:
            try:
                return _unwrap(module, data)
            except EtherscanError as e:
                if RATE_LIMIT_MARKER not in str(
                        e).lower() or attempt == MAX_ATTEMPTS:
                    raise EtherscanError(f"{module}/{action}: {e}") from None
        time.sleep(attempt)
