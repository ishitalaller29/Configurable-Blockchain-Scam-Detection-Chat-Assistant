from datetime import datetime, timezone

from schema import AddressContext


def build_fake_address_context(address: str,
                               chain: str = "ethereum",
                               scenario: str = "suspicious") -> AddressContext:
    # scenario: "suspicious" (low liquidity, unverified, liquidity pulled) or "clean" (verified, established liquidity, no pulls) — lets you sanity-check the Scam Checker against two obviously different inputs.

    now = datetime.now(timezone.utc).isoformat()

    if scenario == "suspicious":
        data = dict(
            chain=chain,
            address=address,
            queried_at=now,
            contract={
                "is_contract": True,
                "bytecode": "0x6080...(truncated fake bytecode)",
                "abi": [],
                "verified_source": False,
                "creation_tx": "0xfaketx0001",
                "creator": "0xfakecreator0001",
            },
            tx_history=[
                {
                    "hash": "0xfaketx0002",
                    "from": "0xfakecreator0001",
                    "to": address,
                    "value": "0.0",
                    "timestamp": now,
                    "method": "createPool",
                },
            ],
            tokens=[
                {
                    "symbol": "FAKECOIN",
                    "contract_address": address,
                    "balance": "1000000",
                    "decimals": 18
                },
            ],
            liquidity=[{
                "pool_address":
                "0xfakepool0001",
                "dex":
                "uniswap_v2",
                "token_pair": ["WETH", "FAKECOIN"],
                "liquidity_usd":
                200.0,
                "liquidity_events": [
                    {
                        "type": "add",
                        "timestamp": now,
                        "amount_usd": 15000.0
                    },
                    {
                        "type": "remove",
                        "timestamp": now,
                        "amount_usd": 14800.0
                    },
                ],
            }],
            fetcher_provenance={
                "contract_fetcher": {
                    "fields": ["contract"],
                    "fetched_at": now
                },
                "tx_history_fetcher": {
                    "fields": ["tx_history"],
                    "fetched_at": now
                },
                "token_fetcher": {
                    "fields": ["tokens"],
                    "fetched_at": now
                },
                "liquidity_fetcher": {
                    "fields": ["liquidity"],
                    "fetched_at": now
                },
            },
        )
    else:  # "clean"
        data = dict(
            chain=chain,
            address=address,
            queried_at=now,
            contract={
                "is_contract": True,
                "bytecode": "0x6080...(truncated fake bytecode)",
                "abi": [{
                    "name": "transfer",
                    "type": "function"
                }],
                "verified_source": True,
                "creation_tx": "0xfaketx0003",
                "creator": "0xfakecreator0002",
            },
            tx_history=[
                {
                    "hash": "0xfaketx0004",
                    "from": "0xfakeuser0001",
                    "to": address,
                    "value": "2.5",
                    "timestamp": now,
                    "method": "transfer",
                },
            ],
            tokens=[
                {
                    "symbol": "SAFEUSD",
                    "contract_address": address,
                    "balance": "500000",
                    "decimals": 18
                },
            ],
            liquidity=[{
                "pool_address": "0xfakepool0002",
                "dex": "uniswap_v2",
                "token_pair": ["WETH", "SAFEUSD"],
                "liquidity_usd": 850000.0,
                "liquidity_events": [],
            }],
            fetcher_provenance={
                "contract_fetcher": {
                    "fields": ["contract"],
                    "fetched_at": now
                },
                "tx_history_fetcher": {
                    "fields": ["tx_history"],
                    "fetched_at": now
                },
                "token_fetcher": {
                    "fields": ["tokens"],
                    "fetched_at": now
                },
                "liquidity_fetcher": {
                    "fields": ["liquidity"],
                    "fetched_at": now
                },
            },
        )

    return AddressContext(**data)
