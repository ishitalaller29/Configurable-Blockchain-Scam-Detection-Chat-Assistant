from typing import List
 
from fetchers.dexscreener import fetch_liquidity_for_context
from schema import LiquidityPool
 
 
def fetch_liquidity(chain: str, address: str) -> List[LiquidityPool]:
    pools, _provenance = fetch_liquidity_for_context(chain, address,
                                                     max_pools=3)
    return [LiquidityPool(**pool) for pool in pools]