from typing import List, Optional

from fetchers.context_builder import FETCHERS, build_address_context
from fetchers.tx_hash_resolver_fetcher import resolve_tx_hash
from schema import AddressContext, BusinessAnalyserOutput, RawInput

# Input kinds a lookup can start from. A token name needs a name resolver, which has no data source yet.
SUPPORTED_INPUTS = ("address", "contract", "tx_hash")


def is_supported(raw_input: Optional[RawInput]) -> bool:
    return raw_input is not None and raw_input.type in SUPPORTED_INPUTS


def resolve_address(raw_input: RawInput, chain: str) -> str:
    if raw_input.type == "tx_hash":
        return resolve_tx_hash(chain, raw_input.value.strip())
    return raw_input.value.strip()


def get_address_context(
        ba_output: BusinessAnalyserOutput,
        requested_fields: Optional[List[str]] = None) -> AddressContext:
    chain = ba_output.chain or "ethereum"
    address = resolve_address(ba_output.raw_input, chain)
    fields = [f for f in requested_fields
              if f in FETCHERS] if requested_fields else None
    return build_address_context(chain, address, fields)
