from fetchers.etherscan import EtherscanError, check_chain, etherscan_request


def resolve_tx_hash(chain: str, tx_hash: str) -> str:
    check_chain(chain)

    #  Only addresses are read here, so nothing is parsed as a number.
    tx = etherscan_request("proxy", "eth_getTransactionByHash", txhash=tx_hash)
    if tx is None:
        raise EtherscanError(f"transaction {tx_hash} not found")

    if tx.get("to"):
        return tx["to"]

    receipt = etherscan_request("proxy",
                                "eth_getTransactionReceipt",
                                txhash=tx_hash)
    if not receipt or not receipt.get("contractAddress"):
        raise EtherscanError(
            f"transaction {tx_hash} has no receipt yet (still pending?)")
    return receipt["contractAddress"]
