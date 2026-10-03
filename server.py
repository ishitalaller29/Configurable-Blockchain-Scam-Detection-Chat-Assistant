"""Local HTTP bridge between the plain HTML/JS chat box and the existing Python pipeline (ChatSession -> BusinessAnalyser -> ScamChecker).

This is the web equivalent of cli.py: it builds the same provider and the same ChatSession, and for every message it calls ChatSession.handle_message() and returns turn.reply, exactly the text the CLI prints after "Bot:". No agent logic, prompts, schema, or routing live here.

Like the interactive CLI, one process holds one conversation, kept in memory and never persisted. The chat box resets it on page load (POST /session/reset) so what the page shows and what the server remembers cannot drift apart - a reload used to clear the visible thread while the server kept answering from history the user could no longer see.

Run:
    uvicorn server:app --port 8000
then open http://localhost:8000/ (the frontend is served from this process).
"""
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
    # Context fields that couldn't be checked this turn.
    missing_fields: List[str] = []
    # Asked because the evidence was insufficient, already included at the end of reply.
    clarifying_questions: List[str] = []
    # Optional quick-reply buttons displayed beneath the assistant response.
    quick_replies: List[str] = []


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
        evidence=[
            Evidence(description=e.description, weight=e.weight)
            for e in det.evidence
        ] if det else [],
        source=turn.detection_source,
        missing_fields=turn.missing_fields,
        clarifying_questions=turn.clarifying_questions,
        quick_replies=turn.quick_replies,
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

@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse(url="/starting-page/index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")
