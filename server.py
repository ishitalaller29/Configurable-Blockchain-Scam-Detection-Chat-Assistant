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
from pydantic import BaseModel

from config import build_default_provider, LLM_CONFIG
from conversation import ChatSession

FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"

app = FastAPI(title="Scam-Detection Chat Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

_provider = build_default_provider()


def _new_session() -> ChatSession:
    return ChatSession(_provider,
                       temperature=LLM_CONFIG["temperature"],
                       max_tokens=LLM_CONFIG["max_tokens"])


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


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse(url="/starting-page/index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")
