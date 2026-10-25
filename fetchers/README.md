# Fetchers

The four Etherscan-backed fetchers are live, built from the project's Etherscan
API Documentation (T1.1–T1.4), and the liquidity fetcher is live on DexScreener.
Token-name resolution is still blocked on a data-source decision.

The admin panel decides which data sources the fetchers may call: Etherscan,
DexScreener or both (see [Turning a data source on or off](#turning-a-data-source-on-or-off)).

| Fetcher | File | API / endpoint | Status |
|---|---|---|---|
| Shared Etherscan request helper | `etherscan.py` | `https://api.etherscan.io/v2/api?chainid=1&module=...&action=...&apikey=...` — the one function every Etherscan call goes through | live |
| Context builder | `context_builder.py` | Runs the context fetchers, fills `fetcher_provenance`, caches per `(chain, address, fetcher)` | live |
| Contract fetcher | `contract_fetcher.py` | `module=proxy`: `eth_getCode`; `module=contract`: `getsourcecode`, `getcontractcreation` | live |
| Transaction history fetcher | `tx_history_fetcher.py` | `module=account&action=txlist` — newest 100, returned oldest first | live |
| Token info fetcher | `token_fetcher.py` | `module=account&action=tokentx` — newest 1000 transfers, balances derived | live |
| Shared DexScreener request helper | `dexscreener.py` | `https://api.dexscreener.com` — `/token-pairs/v1/{chain}/{address}`, falling back to `/latest/dex/pairs/{chain}/{address}` | live |
| Liquidity / paired-pool fetcher | `liquidity_fetcher.py` | DexScreener, through `dexscreener.py` — top 3 pools by liquidity | live |
| Tx-hash resolver fetcher | `tx_hash_resolver_fetcher.py` | `module=proxy`: `eth_getTransactionByHash`, then `eth_getTransactionReceipt` for contract creations | live |


## Usage

```python
from fetchers.context_builder import build_address_context

ctx = build_address_context("ethereum", "0x...")                    # all four context fetchers (minus any whose source is switched off)
ctx = build_address_context("ethereum", "0x...", ["contract"])      # address_info: only what was asked
```

Each fetcher can also be called on its own (`fetch_contract_info(chain, address)` etc.),
but only `build_address_context` caches and records provenance.

## Turning a data source on or off

The admin panel's **Connected sources** list has a toggle for each live data source,
so the assistant can run on Etherscan only, DexScreener only, or both (the default).
At least one has to stay on — with neither, every scam check would run on no data.

The choice is saved in `config/app_config.json`:

```json
"active_data_sources": ["etherscan", "dexscreener"],
```

The admin panel rewrites just that line (`POST /admin/data-sources`), so it has to
stay on one line. A missing key means every live data source. Saving starts a new
conversation, so no earlier reply built from the old sources carries over.

Which source a fetcher calls comes from its `data_source` in the config's `fetchers`
block:

| Data source | Fetchers |
|---|---|
| `etherscan` | contract, transaction history, token info, tx-hash resolver |
| `dexscreener` | liquidity |

A switched-off source is never called. That's checked in two places:

- **`build_address_context`** skips a fetcher whose source is off before the cache
  is read, and records it as `disabled` in `fetcher_provenance`. Data cached while
  the source was on isn't used either.
- **`etherscan_request` and DexScreener's `_get`** — the one function each source's
  calls go through — raise `DataSourceDisabledError` before any request goes out.
  This catches calls that don't go through the context builder, like the tx-hash
  resolver. With Etherscan off, a tx hash can't be resolved, so the assistant asks
  for the address instead.

### What the user sees

- **Source pills**: a verdict ends with an `Etherscan` / `DexScreener` pill for each
  source that was on *and* answered (with several addresses, each address card gets
  its own). They come from `citations(context)` in `context_builder.py`, which only
  counts `ok` provenance entries, so a switched-off or failed source never gets a pill.
- **Not checked**: the fields of a switched-off source are listed under "Not checked"
  and the Scam Checker treats them as unknown, the same as a failed fetcher.

## When a fetcher fails

`build_address_context` never lets one fetcher's failure stop the others. Each
`fetcher_provenance` entry has a `status`, and a `source` (the data source id it calls):

| status | meaning | field value in the context |
|---|---|---|
| `ok` | fetched (has `fetched_at`) | real data |
| `failed` | the fetcher errored — rate limit, network, missing key... (has a short `error`) | default (`[]` / `None`) — means **unknown**, not "none" |
| `unavailable` | no data source yet (a stub fetcher) | default — **unknown** |
| `disabled` | its data source is switched off in the admin panel, so it was never called | default — **unknown** |

Use `missing_fields(context)` to get `{field: status}` for everything that isn't `ok`.
Failures are never cached, so the next message retries them. Only a malformed
address or an unsupported chain still raises, since there's nothing to fetch.

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

