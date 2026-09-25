# Fetchers

The four Etherscan-backed fetchers are live, built from the project's Etherscan
API Documentation (T1.1–T1.4). Liquidity and token-name resolution are still
blocked on a data-source decision.

| Fetcher | File | API / endpoint | Status |
|---|---|---|---|
| Shared Etherscan request helper | `etherscan.py` | `https://api.etherscan.io/v2/api?chainid=1&module=...&action=...&apikey=...` — the one function every Etherscan call goes through | live |
| Context builder | `context_builder.py` | Runs the context fetchers, fills `fetcher_provenance`, caches per `(chain, address, fetcher)` | live |
| Contract fetcher | `contract_fetcher.py` | `module=proxy`: `eth_getCode`; `module=contract`: `getsourcecode`, `getcontractcreation` | live |
| Transaction history fetcher | `tx_history_fetcher.py` | `module=account&action=txlist` — newest 100, returned oldest first | live |
| Token info fetcher | `token_fetcher.py` | `module=account&action=tokentx` — newest 1000 transfers, balances derived | live |
| Liquidity / paired-pool fetcher | `liquidity_fetcher.py` | DexScreener API | Stub |
| Tx-hash resolver fetcher | `tx_hash_resolver_fetcher.py` | `module=proxy`: `eth_getTransactionByHash`, then `eth_getTransactionReceipt` for contract creations | live |


## Usage

```python
from fetchers.context_builder import build_address_context

ctx = build_address_context("ethereum", "0x...")                    # all four context fetchers
ctx = build_address_context("ethereum", "0x...", ["contract"])      # address_info: only what was asked
```

Each fetcher can also be called on its own (`fetch_contract_info(chain, address)` etc.),
but only `build_address_context` caches and records provenance.

## How the Etherscan traps are handled

- **API key**: `ETHERSCAN_API_KEY` from `.env`; missing key raises `ConfigError` before any request.
- **Rate limit**: calls are spaced to 5/sec; a "rate limit reached" reply is retried (1s, then 2s, 3 attempts total). Network errors and 5xx are retried too; 4xx are not. A process-local counter stops calls at 100,000/day.
- **Empty looks like success**: `status "0"` with a `No ... found` message ("No transactions found", "No data found") returns `[]`. Any other `status "0"` raises `EtherscanError`.
- **Proxy calls** have no status/message, so success is result-vs-error presence. An unknown tx hash returns `None`.
- **Malformed input**: Etherscan answers `txlist` for `0x123` with "No transactions found" — identical to an empty wallet. So addresses (`0x` + 40 hex) and tx hashes (`0x` + 64 hex) are checked first and raise `InvalidInputError`.
- **Unverified contracts** still return `status "1"`; the only tell is `SourceCode == ""`, and the ABI is the literal string "Contract source code not verified".
- **Runtime vs creation bytecode**: `contract.bytecode` comes from `eth_getCode`, never `creationBytecode`.
- **EIP-7702 delegated wallets** (e.g. vitalik.eth) have 23-byte code `ef0100` + address. They are `is_contract=False`, and the contract calls are skipped.
- **Contract-creation tx**: `eth_getTransactionByHash` returns the transaction with `to: null` (not a null response); the deployed address is the receipt's `contractAddress`.
- **Token balances** are an estimate from transfer history, flagged in `fetcher_provenance.token_fetcher.note`. Tokens that net to zero or below are dropped.
- **Units**: tx `value` is in ETH, token `balance` is in token units (divided by `decimals`), timestamps are ISO-8601 UTC.
- **Secrets**: the key is in the request URL, so network-error messages from `requests` are never echoed.

