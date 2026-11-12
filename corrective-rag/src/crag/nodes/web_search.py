"""web_search node: DuckDuckGo fallback (no API key) with a timeout and a circuit breaker.

Stop condition: the graph has no edge from here back to grade/decide, so the correction path
runs at most once per question.

Failure handling: a search that errors or exceeds `web_timeout_s` yields an empty list and a
recorded error, never an exception. After FAILURE_THRESHOLD consecutive failures the breaker opens
and web search is skipped for COOLDOWN_S, so a dead search backend does not add its timeout to
every request. State is module-level on purpose: it must outlive a single request.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_core.documents import Document

from ..config import Settings
from ..observability import current_context
from ..state import CRAGState

FAILURE_THRESHOLD = 3
COOLDOWN_S = 60.0


class CircuitBreaker:
    """closed -> open after `threshold` consecutive failures -> half-open after `cooldown_s`.

    Half-open lets exactly ONE trial call through: success closes the breaker, failure reopens it
    for another cooldown. Callers arriving while the trial is in flight are skipped."""

    def __init__(
        self,
        threshold: int = FAILURE_THRESHOLD,
        cooldown_s: float = COOLDOWN_S,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._state = "closed"
        self._open_until = 0.0

    def allow(self) -> bool:
        with self._lock:
            if self._state == "closed":
                return True
            if self._state == "open" and self._clock() >= self._open_until:
                self._state = "half_open"  # this caller is the single trial
                return True
            return False

    def blocked(self) -> bool:
        """Side-effect-free peek: would a call right now be skipped?"""
        with self._lock:
            if self._state == "closed":
                return False
            if self._state == "open" and self._clock() >= self._open_until:
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._state = "closed"

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state == "half_open" or self._failures >= self.threshold:
                self._state = "open"
                self._open_until = self._clock() + self.cooldown_s
                self._failures = 0


breaker = CircuitBreaker()


def web_blocked() -> bool:
    """True while the module breaker would skip a web call (used to skip the rewrite LLM call)."""
    return breaker.blocked()


def reset_breaker() -> None:
    """Close the breaker (tests; also handy for a manual reset)."""
    global breaker
    breaker = CircuitBreaker()


def _ddgs_text(query: str, max_results: int, timeout_s: float) -> list[dict[str, Any]]:
    """The one function that touches ddgs; tests monkeypatch it."""
    from ddgs import DDGS

    return list(DDGS(timeout=max(1, int(timeout_s))).text(query, max_results=max_results))


def _with_timeout(fn: Callable[[], Any], timeout_s: float) -> Any:
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn).result(timeout=timeout_s)
    finally:
        pool.shutdown(wait=False)


def _fail(reason: str) -> None:
    ctx = current_context()
    if ctx is not None:
        ctx.mark_degraded(reason)


def web_search(state: CRAGState, settings: Settings) -> dict:
    steps = [*state.get("steps", []), "web_search"]
    if not settings.web_enabled:
        return {"web_chunks": [], "steps": steps}
    if not breaker.allow():
        _fail("web search skipped: circuit breaker open")
        return {"web_chunks": [], "steps": steps}
    query = state.get("search_query") or state["question"]
    try:
        raw = _with_timeout(
            lambda: _ddgs_text(query, settings.web_max_results, settings.web_timeout_s),
            settings.web_timeout_s,
        )
    except Exception as exc:
        breaker.record_failure()
        _fail(f"web search failed: {type(exc).__name__}: {exc}")
        return {"web_chunks": [], "steps": steps}
    breaker.record_success()
    docs = [
        Document(
            page_content=r.get("body") or "",
            metadata={
                "source": r.get("href") or "",
                "url": r.get("href") or "",
                "title": r.get("title") or "",
                "section": r.get("title") or "",
            },
        )
        for r in raw
        if r.get("body")
    ]
    return {"web_chunks": docs, "steps": steps}
