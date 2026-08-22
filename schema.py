from typing import List, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


class RawInput(BaseModel):
    type: Literal["address", "token_name", "tx_hash", "contract", "unknown"]
    value: str


class BusinessAnalyserOutput(BaseModel):
    in_scope: bool
    request_type: Optional[Literal["scam_check", "address_info",
                                   "general_question"]] = None
    raw_input: Optional[RawInput] = None
    chain: Optional[str] = "ethereum"
    selected_detector: Optional[str] = None
    detector_configured: bool = False
    required_input_type: Optional[Literal["address",
                                          "address_with_context"]] = None
    needs_resolution: bool = False
    resolution_plan: List[str] = Field(default_factory=list)
    direct_response: Optional[str] = None


class Evidence(BaseModel):
    description: str
    weight: float


class DetectionResult(BaseModel):
    label: Literal["scam", "not_scam", "insufficient_evidence"]
    risk_type: Optional[str] = None
    confidence: float
    evidence: List[Evidence] = Field(default_factory=list)
    explanation: str
    reasoning_trace: Optional[str] = None


class ContractInfo(BaseModel):
    is_contract: bool
    bytecode: Optional[str] = None
    abi: List[dict] = Field(default_factory=list)
    verified_source: bool = False
    creation_tx: Optional[str] = None
    creator: Optional[str] = None


class TxRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    hash: str
    from_: str = Field(alias="from")
    to: str
    value: str
    timestamp: str
    method: Optional[str] = None


class TokenBalance(BaseModel):
    symbol: str
    contract_address: str
    balance: str
    decimals: int


class LiquidityEvent(BaseModel):
    type: str
    timestamp: str
    amount_usd: float


class LiquidityPool(BaseModel):
    pool_address: str
    dex: str
    token_pair: List[str]
    liquidity_usd: float
    liquidity_events: List[LiquidityEvent] = Field(default_factory=list)


class AddressContext(BaseModel):
    chain: str
    address: str
    queried_at: str
    contract: Optional[ContractInfo] = None
    tx_history: List[TxRecord] = Field(default_factory=list)
    tokens: List[TokenBalance] = Field(default_factory=list)
    liquidity: List[LiquidityPool] = Field(default_factory=list)
    fetcher_provenance: dict = Field(default_factory=dict)
