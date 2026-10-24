"""The raw data behind a reply, for the page to display.

Every reply can carry a ``raw_data`` object: the identifiers the data sources
returned (transaction hashes, contract, wallet and account addresses), each with
the field it was found in and the source that returned it. The assistant's job
here is only to collect them. How they are shown is up to the UI.

    raw_data = {
        "chain": "ethereum",
        "queried_address": "0x...",          # null if only a tx hash was given and it could not be resolved
        "sources": ["RektRadar", "Etherscan"],
        "items": [
            {"type": "contract_address", "value": "0x...",
             "field": "$.token.address", "source": "RektRadar"},
            ...
        ],
    }

``type`` is one of RAW_DATA_TYPES.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from schema import AddressContext, BusinessAnalyserOutput

TX_HASH = "transaction_hash"
CONTRACT = "contract_address"
WALLET = "wallet_address"
ACCOUNT = "account_address"
ADDRESS = "address"
BLOCK_HASH = "block_hash"
RAW_DATA_TYPES = (TX_HASH, CONTRACT, WALLET, ACCOUNT, ADDRESS, BLOCK_HASH)

# A detector reply can be big. This keeps the raw data small enough to send with every reply.
MAX_ITEMS = 100
MAX_DEPTH = 8

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")

# Words in a field name that say what kind of address its value is. The first group that matches wins, so "contractCreator" counts as a contract, and "walletAddress" as a wallet.
_ADDRESS_KEYWORDS: List[Tuple[str, Tuple[str, ...]]] = [
    (CONTRACT, ("contract", "token", "pool", "pair", "router", "factory")),
    (WALLET, ("wallet",)),
    (ACCOUNT, ("account", "owner", "creator", "deployer", "holder", "sender",
               "recipient", "user", "from", "to")),
]


def _key_words(key: str) -> str:
    return re.sub(r"[^a-z]", "", key.lower())


def _kind_from_name(name: str) -> Optional[str]:
    words = _key_words(name)
    for kind, keywords in _ADDRESS_KEYWORDS:
        if any(k in words for k in keywords):
            return kind
    return None


def classify(key: str, value: str, parent_key: str = "") -> Optional[str]:
    # What a hex value is, from its length and the name of the field it sat in (then the field holding that object, so {"token": {"address": ...}} is a contract). None if it isn't an address or a hash.
    if _HASH_RE.match(value):
        return BLOCK_HASH if "block" in _key_words(key) else TX_HASH
    if _ADDRESS_RE.match(value):
        return _kind_from_name(key) or _kind_from_name(parent_key) or ADDRESS
    return None


class _Collector:

    def __init__(self) -> None:
        self.items: List[Dict[str, str]] = []
        self._by_value: Dict[str, Dict[str, str]] = {}
        self.sources: List[str] = []

    def add(self, kind: str, value: str, field: str, source: str) -> None:
        key = value.lower()
        existing = self._by_value.get(key)
        if existing is not None:
            # The same value found twice: keep the more specific type.
            if existing["type"] == ADDRESS and kind != ADDRESS:
                existing["type"] = kind
            return
        if len(self.items) >= MAX_ITEMS:
            return
        item = {"type": kind, "value": value, "field": field, "source": source}
        self.items.append(item)
        self._by_value[key] = item
        if source not in self.sources:
            self.sources.append(source)

    def scan(self, data: Any, source: str) -> None:
        self._walk(data, "$", "", "", source, 0)

    def _walk(self, node: Any, path: str, key: str, parent_key: str,
              source: str, depth: int) -> None:
        if depth > MAX_DEPTH:
            return
        if isinstance(node, str):
            kind = classify(key, node.strip(), parent_key)
            if kind:
                self.add(kind, node.strip(), path, source)
        elif isinstance(node, dict):
            for k, v in node.items():
                self._walk(v, f"{path}.{k}", str(k), key, source, depth + 1)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                # A list of bare strings takes its name from the field that holds the list ("holders": ["0x..."]).
                self._walk(v, f"{path}[{i}]", key, parent_key, source,
                           depth + 1)


def _add_context(c: _Collector, context: AddressContext) -> None:
    contract = context.contract
    if contract is not None:
        if contract.creation_tx and _HASH_RE.match(contract.creation_tx):
            c.add(TX_HASH, contract.creation_tx, "contract.creation_tx",
                  "Etherscan")
        if contract.creator and _ADDRESS_RE.match(contract.creator):
            c.add(ACCOUNT, contract.creator, "contract.creator", "Etherscan")
    for i, tx in enumerate(context.tx_history):
        if _HASH_RE.match(tx.hash):
            c.add(TX_HASH, tx.hash, f"tx_history[{i}].hash", "Etherscan")
        if _ADDRESS_RE.match(tx.from_):
            c.add(ACCOUNT, tx.from_, f"tx_history[{i}].from", "Etherscan")
        if _ADDRESS_RE.match(tx.to):
            c.add(ADDRESS, tx.to, f"tx_history[{i}].to", "Etherscan")
    for i, token in enumerate(context.tokens):
        if _ADDRESS_RE.match(token.contract_address):
            c.add(CONTRACT, token.contract_address,
                  f"tokens[{i}].contract_address", "Etherscan")
    for i, pool in enumerate(context.liquidity):
        if _ADDRESS_RE.match(pool.pool_address):
            c.add(CONTRACT, pool.pool_address, f"liquidity[{i}].pool_address",
                  "DexScreener")


def build_raw_data(
        ba_output: BusinessAnalyserOutput,
        context: Optional[AddressContext] = None,
        detector_reply: Optional[Tuple[str, Any]] = None,
        resolved_address: Optional[str] = None) -> Optional[Dict[str, Any]]:
    # detector_reply is (detector name, the detector's reply as parsed JSON), when a configured detector answered this turn. resolved_address is the address a transaction hash resolved to, when no context was fetched. Returns None when the message wasn't about an address.
    raw_input = ba_output.raw_input
    if raw_input is None or raw_input.type not in ("address", "contract",
                                                   "tx_hash"):
        return None
    given = raw_input.value.strip()
    chain = (context.chain if context else ba_output.chain) or "ethereum"
    queried = context.address if context else (
        given if raw_input.type != "tx_hash" else resolved_address)

    # What the address is, as far as the data says: a contract if Etherscan found code there, a wallet if it found none.
    queried_kind = ADDRESS
    if raw_input.type == "contract":
        queried_kind = CONTRACT
    elif context is not None and context.contract is not None:
        queried_kind = CONTRACT if context.contract.is_contract else WALLET

    c = _Collector()
    if raw_input.type == "tx_hash":
        if _HASH_RE.match(given):
            c.add(TX_HASH, given, "input", "user input")
        if queried:
            c.add(queried_kind, queried, "resolved from the transaction hash",
                  "Etherscan")
    elif queried and _ADDRESS_RE.match(queried):
        c.add(queried_kind, queried, "input", "user input")

    if detector_reply is not None:
        name, reply = detector_reply
        c.scan(reply, name)
    if context is not None:
        _add_context(c, context)

    return {
        "chain": chain,
        "queried_address": queried,
        "sources": c.sources,
        "items": c.items,
    }


def merge_raw_data(
        parts: List[Optional[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    parts = [p for p in parts if p]
    if not parts:
        return None
    c = _Collector()
    for part in parts:
        for item in part["items"]:
            c.add(item["type"], item["value"], item["field"], item["source"])
    return {
        "chain": parts[0]["chain"],
        "queried_address": parts[0]["queried_address"],
        "queried_addresses": [
            p["queried_address"] for p in parts if p["queried_address"]
        ],
        "sources": c.sources,
        "items": c.items,
    }
