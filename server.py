"""Local HTTP bridge between the plain HTML/JS chat box and the existing Python pipeline (ChatSession -> BusinessAnalyser -> ScamChecker).

This is the web equivalent of cli.py: it builds the same provider and the same ChatSession, and for every message it calls ChatSession.handle_message() and returns turn.reply, exactly the text the CLI prints after "Bot:". No agent logic, prompts, schema, or routing live here.

Like the interactive CLI, one process holds one conversation, kept in memory and never persisted. The chat box resets it on page load (POST /session/reset) so what the page shows and what the server remembers cannot drift apart - a reload used to clear the visible thread while the server kept answering from history the user could no longer see.

Run:
    uvicorn server:app --port 8000
then open http://localhost:8000/ (the frontend is served from this process).
"""
import os
import threading
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from typing import Dict

from config import (AGENT_KEYS, FUNCTIONAL_PROVIDERS, LLM_CONFIG,
                    SUPPORTED_PROVIDERS, build_provider_for_agent,
                    load_agent_config, save_agent_config)
from config_loader import (ConfigError, get_active_detector, list_detectors,
                           set_active_detector)
from conversation import ChatSession

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"

app = FastAPI(title="Scam-Detection Chat Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

_agent_config = load_agent_config()
_ba_provider = build_provider_for_agent("business_analyser", _agent_config)
_sc_provider = build_provider_for_agent("scam_checker", _agent_config)


def _new_session() -> ChatSession:
    return ChatSession(_ba_provider,
                       temperature=LLM_CONFIG["temperature"],
                       max_tokens=LLM_CONFIG["max_tokens"],
                       ba_provider=_ba_provider,
                       sc_provider=_sc_provider)


_session = _new_session()
_session_lock = threading.Lock()


class ChatRequest(BaseModel):
    message: str


class Evidence(BaseModel):
    description: str
    weight: float


class AddressResult(BaseModel):
    input: str
    input_type: str
    address: Optional[str] = None
    reply: str
    label: Optional[str] = None
    confidence: Optional[float] = None
    risk_type: Optional[str] = None
    evidence: List[Evidence] = []
    source: Optional[str] = None
    detector_name: Optional[str] = None
    missing_fields: List[str] = []


def _evidence(det) -> List[Evidence]:
    return [
        Evidence(description=e.description, weight=e.weight)
        for e in det.evidence
    ] if det else []


class ChatResponse(BaseModel):
    # The text the CLI prints.
    reply: str
    in_scope: bool
    request_type: Optional[str] = None
    label: Optional[str] = None
    confidence: Optional[float] = None
    risk_type: Optional[str] = None
    evidence: List[Evidence] = []
    source: Optional[str] = None
    detector_name: Optional[str] = None
    # Context fields that couldn't be checked this turn.
    missing_fields: List[str] = []
    # Asked because the evidence was insufficient, already included at the end of reply.
    clarifying_questions: List[str] = []
    # Optional quick-reply buttons displayed beneath the assistant response.
    quick_replies: List[str] = []
    # The raw identifiers the data sources returned for this reply (see raw_data.py): {chain, queried_address, sources, items: [{type, value, field, source}]}. Null when the message wasn't about an address. type is transaction_hash, contract_address, wallet_address, account_address, address or block_hash.
    raw_data: Optional[dict] = None
    results: List[AddressResult] = []
    skipped_inputs: List[str] = []


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    with _session_lock:
        turn = _session.handle_message(req.message)

    ba = turn.ba_output
    det = turn.detection_result
    return ChatResponse(
        reply=turn.reply,
        in_scope=ba.in_scope,
        request_type=ba.request_type,
        label=det.label if det else None,
        confidence=det.confidence if det else None,
        risk_type=det.risk_type if det else None,
        evidence=_evidence(det),
        source=turn.detection_source,
        detector_name=turn.detector_name,
        missing_fields=turn.missing_fields,
        clarifying_questions=turn.clarifying_questions,
        quick_replies=turn.quick_replies,
        raw_data=turn.raw_data,
        results=[
            AddressResult(
                input=c.input.value,
                input_type=c.input.type,
                address=c.address,
                reply=c.reply,
                label=c.detection_result.label if c.detection_result else None,
                confidence=(c.detection_result.confidence
                            if c.detection_result else None),
                risk_type=(c.detection_result.risk_type
                           if c.detection_result else None),
                evidence=_evidence(c.detection_result),
                source=c.detection_source,
                detector_name=c.detector_name,
                missing_fields=c.missing_fields,
            ) for c in turn.address_checks
        ],
        skipped_inputs=turn.skipped_inputs,
    )


class SessionResetResponse(BaseModel):
    ok: bool


@app.post("/session/reset", response_model=SessionResetResponse)
def reset_session() -> SessionResetResponse:
    # Start a fresh conversation, the way quitting and relaunching the CLI does.
    global _session
    with _session_lock:
        _session = _new_session()
    return SessionResetResponse(ok=True)


class AgentLLMConfig(BaseModel):
    provider: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: str


class LLMConfigResponse(BaseModel):
    config: Dict[str, AgentLLMConfig]
    supported_providers: List[str]
    functional_providers: List[str]


class LLMConfigUpdateRequest(BaseModel):
    config: Dict[str, AgentLLMConfig]


@app.get("/admin/llm-config", response_model=LLMConfigResponse)
def get_llm_config() -> LLMConfigResponse:
    return LLMConfigResponse(
        config=load_agent_config(),
        supported_providers=list(SUPPORTED_PROVIDERS),
        functional_providers=list(FUNCTIONAL_PROVIDERS),
    )


@app.post("/admin/llm-config", response_model=LLMConfigResponse)
def update_llm_config(req: LLMConfigUpdateRequest) -> LLMConfigResponse:
    # Rejects an unknown provider value outright rather than silently storing
    # it - the admin UI only ever offers SUPPORTED_PROVIDERS, so this should
    # only trip on a malformed request, not a user's real selection.
    new_config = {}
    for key in AGENT_KEYS:
        agent_cfg = req.config.get(key)
        if agent_cfg is None:
            continue
        if agent_cfg.provider not in SUPPORTED_PROVIDERS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown provider '{agent_cfg.provider}' for {key}")
        new_config[key] = agent_cfg.model_dump()

    merged = load_agent_config()
    merged.update(new_config)
    save_agent_config(merged)

    # Rebuild the providers actually in use so a save takes effect
    # immediately, without restarting the server.
    global _ba_provider, _sc_provider, _session
    _ba_provider = build_provider_for_agent("business_analyser", merged)
    _sc_provider = build_provider_for_agent("scam_checker", merged)
    with _session_lock:
        _session = _new_session()

    return LLMConfigResponse(
        config=merged,
        supported_providers=list(SUPPORTED_PROVIDERS),
        functional_providers=list(FUNCTIONAL_PROVIDERS),
    )


# Active detector dropdown. Only the four real detectors are offered
SELECTABLE_DETECTORS = ("rektradar", "ethxpose", "honeypotscan", "recon")


class DetectorChoice(BaseModel):
    id: str
    name: Optional[str] = None
    status: Optional[str] = None
    is_llm_based: bool = False


class DetectorConfigResponse(BaseModel):
    # None = no detector, so scam checks go to the Scam Checker.
    active_detector: Optional[str] = None
    detectors: List[DetectorChoice]
    # True when the ACTIVE_DETECTOR env var is set
    env_override: bool = False


class DetectorConfigUpdateRequest(BaseModel):
    active_detector: Optional[str] = None


def _detector_config_response() -> DetectorConfigResponse:
    active = get_active_detector()
    return DetectorConfigResponse(
        active_detector=active[0] if active else None,
        detectors=[
            DetectorChoice(**d) for d in list_detectors()
            if d["id"] in SELECTABLE_DETECTORS
        ],
        env_override=bool(os.environ.get("ACTIVE_DETECTOR")),
    )


@app.get("/admin/detector", response_model=DetectorConfigResponse)
def get_detector_config() -> DetectorConfigResponse:
    return _detector_config_response()


@app.post("/admin/detector", response_model=DetectorConfigResponse)
def update_detector_config(
        req: DetectorConfigUpdateRequest) -> DetectorConfigResponse:
    detector_id = req.active_detector
    if detector_id is not None and detector_id not in SELECTABLE_DETECTORS:
        raise HTTPException(status_code=400,
                            detail=f"Unknown detector '{detector_id}'")
    try:
        set_active_detector(detector_id)
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # ChatSession reads the active detector when it is built, so start a new one for the change to take effect without restarting the server.
    global _session
    with _session_lock:
        _session = _new_session()

    return _detector_config_response()


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse(url="/starting-page/index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")
