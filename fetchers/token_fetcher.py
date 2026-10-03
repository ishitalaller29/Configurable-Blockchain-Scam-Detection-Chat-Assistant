from decimal import Decimal
from typing import List

from fetchers.etherscan import check_chain, etherscan_request
from schema import TokenBalance

MAX_TRANSFERS = 1000
ESTIMATE_NOTE = (
    f"Balances are estimates: incoming minus outgoing over the {MAX_TRANSFERS} most "
    "recent token transfers, not an on-chain balance read.")


def fetch_token_balances(chain: str, address: str) -> List[TokenBalance]:
    check_chain(chain)

    transfers = etherscan_request(
        "account",
        "tokentx",
        address=address,
        page=1,
        offset=MAX_TRANSFERS,
        sort="desc",
    )

    me = address.lower()
    running: dict = {}
    for row in transfers:
        entry = running.setdefault(
            row["contractAddress"].lower(), {
                "symbol": row.get("tokenSymbol", ""),
                "decimals": int(row.get("tokenDecimal") or 0),
                "raw_balance": 0,
            })
        amount = int(row["value"])
        if row["to"].lower() == me:
            entry["raw_balance"] += amount
        if row["from"].lower() == me:
            entry["raw_balance"] -= amount

    # Zero means everything was sent back out; negative means the incoming side is older than the transfers fetched. Neither is a token currently held.
    return [
        TokenBalance(
            symbol=v["symbol"],
            contract_address=contract_address,
            balance=format((Decimal(v["raw_balance"]) /
                            (Decimal(10)**v["decimals"])).normalize(), "f"),
            decimals=v["decimals"],
        ) for contract_address, v in running.items() if v["raw_balance"] > 0
    ]
