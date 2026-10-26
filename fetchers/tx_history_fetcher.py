from datetime import datetime, timezone
from decimal import Decimal
from typing import List

from fetchers.etherscan import check_chain, etherscan_request
from schema import TxRecord

MAX_TXS = 100
WEI_PER_ETH = Decimal(10)**18


def wei_to_eth(wei: str) -> str:
    eth = Decimal(wei) / WEI_PER_ETH
    return format(eth.normalize(), "f") if eth else "0"


def unix_to_iso(timestamp: str) -> str:
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat()


def fetch_tx_history(chain: str, address: str) -> List[TxRecord]:
    check_chain(chain)

    # sort=desc so the one page we fetch holds the NEWEST transactions. A zero-tx address comes back as [] not an error
    rows = etherscan_request(
        "account",
        "txlist",
        address=address,
        page=1,
        offset=MAX_TXS,
        sort="desc",
    )

    records = [
        TxRecord(
            hash=row["hash"],
            from_=row["from"],
            to=row["to"],  # "" for a contract-creation tx
            value=wei_to_eth(row["value"]),
            timestamp=unix_to_iso(row["timeStamp"]),
            method=row.get("functionName", "").split("(")[0] or None,
        ) for row in rows
    ]
    # Oldest first, so tx_history[-1] is the latest one (conversation.py relies on this)
    records.reverse()
    return records
