import json

from fetchers.etherscan import check_chain, etherscan_request
from schema import ContractInfo

# EIP-7702 delegated wallet: 23 bytes = ef0100 + a 20-byte address.
DELEGATION_PREFIX = "0xef0100"
DELEGATION_CODE_LENGTH = 2 + 23 * 2


def is_delegated_eoa(code: str) -> bool:
    return code.lower().startswith(DELEGATION_PREFIX) and len(
        code) == DELEGATION_CODE_LENGTH


def fetch_contract_info(chain: str, address: str) -> ContractInfo:
    check_chain(chain)

    # Runtime bytecode (eth_getCode), never the creation bytecode that getcontractcreation also returns
    code = etherscan_request("proxy",
                             "eth_getCode",
                             address=address,
                             tag="latest")

    # A plain wallet has code "0x"; an EIP-7702 delegated wallet has code but is still a wallet. Neither has source or a creation tx, so stop here.
    if code in ("0x", "", None) or is_delegated_eoa(code):
        return ContractInfo(is_contract=False,
                            bytecode=code if code not in ("0x", "") else None)

    source = etherscan_request("contract", "getsourcecode", address=address)[0]
    # status can read "1"/"OK" for an unverified contract - SourceCode == "" is the actual tell. Its ABI is then the literal "Contract source code# not verified", not JSON.
    verified_source = source.get("SourceCode", "") != ""
    abi = []
    if verified_source:
        try:
            abi = json.loads(source["ABI"])
        except (KeyError, ValueError):
            abi = []

    # Some contracts have no creation record: that comes back as an empty result, not an error.
    creations = etherscan_request("contract",
                                  "getcontractcreation",
                                  contractaddresses=address)
    creation = creations[0] if creations else {}

    return ContractInfo(
        is_contract=True,
        bytecode=code,
        abi=abi,
        verified_source=verified_source,
        creation_tx=creation.get("txHash") or None,
        creator=creation.get("contractCreator") or None,
    )
