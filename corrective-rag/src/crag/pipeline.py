"""Public API: `answer(question, settings=None, *, engine=None) -> Answer`.

Contract: raises ONLY ValueError for invalid input. Every runtime fault (provider down, parse
errors, web down, a bug inside a node) is caught, recorded in `Answer.errors`, and turned into a
degraded answer or abstention. A caller (API, eval harness, UI) never needs a try/except for it.

Performance: an `Engine` owns the expensive long-lived pieces (LLM client, retriever with its
Chroma client and BM25 model, compiled graph). `answer()` reuses one engine per Settings object
instead of rebuilding them per request.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Any, Literal

from pydantic import BaseModel, Field

from .config import Settings, get_settings
from .graph import build_graph
from .guardrails import validate_question
from .llm import LLMClient
from .nodes.generate import ABSTAIN_MESSAGE
from .observability import run_context, write_trace
from .retrieval import Retriever

log = logging.getLogger("crag.pipeline")


class Citation(BaseModel):
    id: int
    source: str
    section: str = ""
    url: str | None = None
    snippet: str = ""


class ContextDoc(BaseModel):
    """A document exactly as passed to the generation prompt; `id` matches the [N] citations."""

    id: int
    source: str
    section: str = ""
    url: str | None = None
    text: str
    origin: Literal["local", "web"]


class RetrievedChunk(BaseModel):
    """Summary of one locally retrieved chunk, in rank order (the eval harness scores these)."""

    chunk_id: str
    source: str
    section: str = ""
    text: str
    score: float


class Answer(BaseModel):
    """One pipeline result.

    `context` is the documents shown to the generator (ids match the [N] citations). It may be
    non-empty when `abstained` is true: the model saw documents and declined to answer from them.
    `retrieved` is local retrieval in rank order, before grading."""

    answer: str
    citations: list[Citation] = Field(default_factory=list)
    route: str  # local | local+web | web | abstain
    abstained: bool
    degraded: bool
    errors: list[str] = Field(default_factory=list)
    retrieved: list[RetrievedChunk] = Field(default_factory=list)
    context: list[ContextDoc] = Field(default_factory=list)
    latency_ms: float
    llm_calls: int
    retries: int
    trace_id: str


class Engine:
    """Long-lived, reusable pipeline pieces for one Settings object."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.client = LLMClient(self.settings)
        self.retriever = Retriever(self.settings)
        self.graph = build_graph(
            self.settings, client=self.client, retriever=self.retriever, check_index=True
        )


_lock = threading.Lock()
_engines: dict[str, Engine] = {}  # settings fingerprint -> engine (insertion-ordered, bounded)
_MAX_ENGINES = 8


def fingerprint(settings: Settings) -> str:
    """Stable identity for a configuration: equal configs share an engine.

    The API key is hashed, never stored or logged raw, so a key change still yields a new engine."""
    key = settings.nvidia_api_key.get_secret_value() if settings.nvidia_api_key else ""
    digest = hashlib.sha256(key.encode()).hexdigest()
    return settings.model_dump_json(exclude={"nvidia_api_key"}) + digest


def reset_engines() -> None:
    """Drop cached engines (tests; or after swapping provider factories)."""
    with _lock:
        _engines.clear()


def _engine_for(settings: Settings | None) -> Engine:
    # settings=None re-reads the environment/.env each call, so config edits take effect.
    s = settings or get_settings()
    fp = fingerprint(s)
    with _lock:
        eng = _engines.get(fp)
        if eng is None:
            if len(_engines) >= _MAX_ENGINES:
                _engines.pop(next(iter(_engines)))  # evict oldest
            eng = _engines[fp] = Engine(s)
        return eng


def answer(
    question: str, settings: Settings | None = None, *, engine: Engine | None = None
) -> Answer:
    eng = engine or _engine_for(settings)
    s = eng.settings
    q = validate_question(question, s.max_question_chars)  # the only raise
    with run_context() as ctx:
        state: dict[str, Any] = {}
        try:
            # stream(values) so a mid-run crash still leaves the last complete state (retrieved
            # chunks included) instead of nothing.
            for snapshot in eng.graph.stream({"question": q, "steps": []}, stream_mode="values"):
                state = snapshot
        except Exception as exc:  # never let a runtime fault escape
            log.exception("pipeline failed")
            ctx.mark_degraded(f"pipeline failure: {type(exc).__name__}: {exc}")
        try:
            write_trace(ctx, s.trace_dir)
        except Exception:  # tracing must never break a request
            log.warning("trace write failed")
        return Answer(
            answer=state.get("answer") or ABSTAIN_MESSAGE,
            citations=[Citation(**c) for c in state.get("citations", [])],
            route=state.get("route", "abstain"),
            abstained=state.get("abstained", True),
            degraded=ctx.degraded,
            errors=list(ctx.errors),
            retrieved=[
                RetrievedChunk(
                    chunk_id=c.chunk_id,
                    source=str(c.metadata.get("source", "")),
                    section=str(c.metadata.get("section", "")),
                    text=c.text,
                    score=c.score,
                )
                for c in state.get("chunks", [])
            ],
            context=[ContextDoc(**d) for d in state.get("context", [])],
            latency_ms=round(ctx.latency_ms, 1),
            llm_calls=len(ctx.llm_calls),
            retries=ctx.retries,
            trace_id=ctx.trace_id,
        )
