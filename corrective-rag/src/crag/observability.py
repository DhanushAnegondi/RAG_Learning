"""Per-request observability: a RunContext carried via contextvars, spans, JSON logs, JSONL traces.

Why contextvars: nodes and the LLM client are deep in the call stack; passing a context object
through every signature would pollute them. A contextvar follows the request across threads that
copy the context (the grader's thread pool does) without any global mutable state.

Secrets: nothing here records request bodies, headers, or settings. Errors are stored as
`ExcType: message` strings, and `redact()` scrubs anything that looks like an NVIDIA key.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_KEY_RE = re.compile(r"nvapi-[A-Za-z0-9_\-]+")


def redact(text: str) -> str:
    """Scrub anything shaped like an NVIDIA API key from a string before it is stored/logged."""
    return _KEY_RE.sub("nvapi-***", text)


@dataclass
class Span:
    name: str
    latency_ms: float
    error: str | None = None


@dataclass
class LLMCall:
    purpose: str
    model: str
    latency_ms: float
    retries: int = 0
    fallback_used: bool = False
    error: str | None = None


@dataclass
class RunContext:
    """Everything worth knowing about one request. Mutated from worker threads, so guarded."""

    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started: float = field(default_factory=time.perf_counter)
    spans: list[Span] = field(default_factory=list)
    llm_calls: list[LLMCall] = field(default_factory=list)
    retries: int = 0
    fallbacks: int = 0
    errors: list[str] = field(default_factory=list)
    degraded: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_span(self, span: Span) -> None:
        with self._lock:
            self.spans.append(span)

    def record_llm_call(self, call: LLMCall) -> None:
        with self._lock:
            self.llm_calls.append(call)
            self.retries += call.retries
            if call.fallback_used:
                self.fallbacks += 1

    def record_error(self, message: str) -> None:
        with self._lock:
            self.errors.append(redact(message))

    def mark_degraded(self, reason: str | None = None) -> None:
        with self._lock:
            self.degraded = True
            if reason:
                self.errors.append(redact(reason))

    @property
    def latency_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000.0

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "trace_id": self.trace_id,
                "latency_ms": round(self.latency_ms, 1),
                "spans": [vars(s) for s in self.spans],
                "llm_calls": [vars(c) for c in self.llm_calls],
                "retries": self.retries,
                "fallbacks": self.fallbacks,
                "errors": list(self.errors),
                "degraded": self.degraded,
            }


_current: contextvars.ContextVar[RunContext | None] = contextvars.ContextVar(
    "crag_run_context", default=None
)


def current_context() -> RunContext | None:
    return _current.get()


@contextmanager
def run_context() -> Iterator[RunContext]:
    """Open a fresh RunContext for the duration of one request."""
    ctx = RunContext()
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


@contextmanager
def span(name: str) -> Iterator[None]:
    """Time a node. Records into the active context if there is one; a no-op otherwise, so
    nodes stay callable in isolation (tests, notebooks)."""
    start = time.perf_counter()
    err: str | None = None
    try:
        yield
    except BaseException as exc:
        err = redact(f"{type(exc).__name__}: {exc}")
        raise
    finally:
        ctx = _current.get()
        if ctx is not None:
            ctx.add_span(Span(name, round((time.perf_counter() - start) * 1000.0, 1), err))


class JsonFormatter(logging.Formatter):
    """One JSON object per log line, with the active trace id attached."""

    def format(self, record: logging.LogRecord) -> str:
        ctx = _current.get()
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        if ctx is not None:
            payload["trace_id"] = ctx.trace_id
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    """Install the JSON formatter on the `crag` logger (idempotent)."""
    logger = logging.getLogger("crag")
    if any(isinstance(h.formatter, JsonFormatter) for h in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def write_trace(ctx: RunContext, trace_dir: str | Path) -> Path | None:
    """Append one JSON line for this request to `<trace_dir>/<utc-date>.jsonl`.

    Tracing must never break a request, so IO failure returns None instead of raising."""
    try:
        d = Path(trace_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ctx.to_dict(), ensure_ascii=False) + "\n")
        return path
    except OSError:
        return None
