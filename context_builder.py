import logging
from datetime import datetime, timezone
from typing import Optional

import requests

from dexscreener_fetcher import (fetch_liquidity_for_context,
                                 pick_canonical_pair, search_pairs)
from fake_data import build_fake_address_context
from schema import AddressContext

logger = logging.getLogger(__name__)

DEFAULT_CHAIN = "ethereum"

def _resolve_name(query: str, chain: Optional[str]) -> tuple[str, str]:
    pairs = search_pairs(query)
    if chain:
        pairs = [p for p in pairs if (p.get("chainId") or "") == chain]
    q = query.strip().lower()
    matching = [p for p in pairs
                if ((p.get("baseToken") or {}).get("symbol") or "").lower() == q
                or ((p.get("baseToken") or {}).get("name") or "").lower() == q]
    best = pick_canonical_pair(matching or pairs)
    if not best:
        return chain or DEFAULT_CHAIN, query
    address = (best.get("baseToken") or {}).get("address") or query
    return best.get("chainId") or chain or DEFAULT_CHAIN, address

def build_address_context(address: str,
                          chain: Optional[str] = None,
                          scenario: str = "suspicious",
                          liquidity_source: str = "fake") -> AddressContext:
    if liquidity_source == "fake":
        return build_fake_address_context(address, chain or DEFAULT_CHAIN,
                                          scenario)

    if liquidity_source != "dexscreener":
        raise ValueError(f"Unknown liquidity_source: {liquidity_source}")

    liquidity, provenance = [], {}
    try:
        if not address.lower().startswith("0x"):
            chain, address = _resolve_name(address, chain)
        chain = chain or DEFAULT_CHAIN
        liquidity, provenance = fetch_liquidity_for_context(chain, address)
    except requests.RequestException as e:
        chain = chain or DEFAULT_CHAIN
        logger.warning("DexScreener lookup failed for %s on %s: %s",
                       address, chain, e)

    return AddressContext(
        chain=chain,
        address=address,
        queried_at=datetime.now(timezone.utc).isoformat(),
        liquidity=liquidity,
        fetcher_provenance=provenance,
    )