from typing import Any, Dict, List, Optional, Literal
from pydantic import (BaseModel, Field, ConfigDict, field_validator,
                      model_validator)

Label = Literal["scam", "not_scam", "insufficient_evidence"]
LABEL_VALUES = ("scam", "not_scam", "insufficient_evidence")
RequiredInputType = Literal["address", "address_with_context"]
RISK_TYPE_MAX_LEN = 64


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
    requested_fields: List[str] = Field(default_factory=list)

    expertise_tier: Optional[Literal["beginner", "intermediate",
                                     "professional"]] = None
    use_case: Optional[Literal["investment", "investigative_legal",
                               "compliance_risk"]] = None
    needs_clarification: bool = False
    raw_inputs: List[RawInput] = Field(default_factory=list)

    @field_validator("raw_inputs", mode="before")
    @classmethod
    def _null_raw_inputs(cls, value):
        return value or []

    @model_validator(mode="after")
    def _sync_raw_inputs(self):
        if not self.raw_inputs and self.raw_input is not None:
            self.raw_inputs = [self.raw_input]
        seen, distinct = set(), []
        for raw in self.raw_inputs:
            key = (raw.type, raw.value.strip().lower())
            if key not in seen:
                seen.add(key)
                distinct.append(raw)
        self.raw_inputs = distinct
        if distinct:
            self.raw_input = distinct[0]
        return self


class Evidence(BaseModel):
    description: str
    weight: float


class DetectionResult(BaseModel):
    label: Label
    risk_type: Optional[str] = None
    confidence: float
    evidence: List[Evidence] = Field(default_factory=list)
    explanation: str
    reasoning_trace: Optional[str] = None


class DetectionResultCore(BaseModel):
    label: Label
    risk_type: Optional[str] = Field(default=None,
                                     max_length=RISK_TYPE_MAX_LEN)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[Evidence] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def _weights_in_range(cls, evidence: List[Evidence]) -> List[Evidence]:
        for item in evidence:
            if not 0.0 <= item.weight <= 1.0:
                raise ValueError(
                    f"evidence weight {item.weight} is outside [0, 1]")
        return evidence


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


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["header"] = "header"
    header_name: str
    value_template: str = "{api_key}"
    api_key: str
    optional: bool = False


class RequestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body_template: Dict[str, Any] = Field(default_factory=dict)


class RangeRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gte: Optional[float] = None
    gt: Optional[float] = None
    lte: Optional[float] = None
    lt: Optional[float] = None
    value: Label


class LabelValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map: Dict[str, Label] = Field(default_factory=dict)


class LabelOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    contains: Optional[List[str]] = None
    equals: Optional[Any] = None
    min_items: Optional[int] = Field(default=None, ge=0)
    max_items: Optional[int] = Field(default=None, ge=0)
    value: Label

    @model_validator(mode="after")
    def _one_condition(self):
        counts_items = (self.min_items is not None
                        or self.max_items is not None)
        conditions = [
            self.contains is not None, self.equals is not None, counts_items
        ]
        if sum(conditions) != 1:
            raise ValueError(
                "a label override needs exactly one condition: 'contains', "
                "'equals', or 'min_items'/'max_items'")
        if (self.min_items is not None and self.max_items is not None
                and self.min_items > self.max_items):
            raise ValueError(
                "a label override's 'min_items' can't be above 'max_items'")
        if self.contains is not None and not self.contains:
            raise ValueError("a label override's 'contains' can't be empty")
        if not isinstance(self.equals, (type(None), str, int, float, bool)):
            raise ValueError("a label override's 'equals' must be a plain "
                             "value (text, number or true/false)")
        return self


class LabelMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    overrides: List[LabelOverride] = Field(default_factory=list)
    value: Optional[LabelValue] = None
    ranges: List[RangeRule] = Field(default_factory=list)
    fallback: Label = "insufficient_evidence"


class RiskTypeMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    max_length: int = Field(default=RISK_TYPE_MAX_LEN, gt=0)


class ExplanationMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


class ConfidenceMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    scale: float = Field(default=1.0, gt=0)
    default: float = Field(default=0.0, ge=0.0, le=1.0)
    measures: Literal["label", "risk", "safety"] = "label"


class EvidenceItemMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    title: Optional[str] = None
    weight: Optional[str] = None
    weight_map: Dict[str, float] = Field(default_factory=dict)

    @field_validator("weight_map")
    @classmethod
    def _map_weights_in_range(cls, weight_map: Dict[str, float]):
        for word, weight in weight_map.items():
            if not 0.0 <= weight <= 1.0:
                raise ValueError(
                    f"weight_map[{word!r}] must be between 0 and 1")
        return weight_map


class EvidenceCode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    weight: float = Field(ge=0.0, le=1.0)


class EvidenceMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["list", "code_list"]
    list_path: str
    code_path: Optional[str] = None
    item: Optional[EvidenceItemMapping] = None
    default_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    codes: Dict[str, EvidenceCode] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _mode_needs_its_table(self):
        if self.mode == "list" and self.item is None:
            raise ValueError("evidence mode 'list' needs an 'item' mapping")
        return self


class ResponseMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: LabelMapping
    risk_type: Optional[RiskTypeMapping] = None
    confidence: Optional[ConfidenceMapping] = None
    evidence: Optional[EvidenceMapping] = None
    explanation: Optional[ExplanationMapping] = None


class DetectorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    mode: Literal["template", "generic"]
    endpoint: str
    method: Literal["GET", "POST"] = "POST"
    required_input_type: RequiredInputType
    is_llm_based: bool = False
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    auth: Optional[AuthConfig] = None
    request: Optional[RequestConfig] = None
    response_mapping: Optional[ResponseMapping] = None
