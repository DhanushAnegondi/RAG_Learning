"""Error taxonomy for provider calls, and `classify()` to map real exceptions onto it.

Why: retry policy depends on the *kind* of failure. A 429 or timeout is worth retrying; a 401 or a
malformed request never gets better by waiting; an unparseable structured output needs a different
remedy (ask again as plain text). Everything in llm.py keys off these three classes.
"""

from __future__ import annotations

import re


class CragError(Exception):
    """Base class for classified provider failures."""


class TransientError(CragError):
    """Worth retrying: timeouts, connection resets, 429, 5xx."""


class PermanentError(CragError):
    """Retrying cannot help: bad request, auth, forbidden, model not found."""

    def __init__(self, message: str = "", *, status: int | None = None):
        super().__init__(message)
        self.status = status

    @property
    def model_specific(self) -> bool:
        """404 (model not found / not entitled) is specific to one model: the next may work."""
        return self.status == 404


class ParseError(CragError):
    """Empty or schema-invalid structured output."""


_STATUS_RE = re.compile(r"\[(\d{3})\]|\b(?:status(?:[_ ]code)?|http)\D{0,3}(\d{3})\b", re.I)
_PARSE_HINTS = ("json", "parse", "structured output", "validation", "empty")


def status_of(exc: BaseException) -> int | None:
    """Best-effort HTTP status from an exception, however the SDK surfaced it.

    Order: explicit attributes (httpx/requests/openai-style), then `response.status_code`, then
    the `[429] Too Many Requests` pattern langchain-nvidia-ai-endpoints puts in its message."""
    for attr in ("status_code", "status", "http_status"):
        v = getattr(exc, attr, None)
        if isinstance(v, int) and 100 <= v < 600:
            return v
    v = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(v, int) and 100 <= v < 600:
        return v
    m = _STATUS_RE.search(str(exc))
    if m:
        v = int(m.group(1) or m.group(2))
        return v if 100 <= v < 600 else None
    return None


def classify(exc: BaseException) -> type[CragError]:
    """Map any exception to TransientError / PermanentError / ParseError.

    Unknown exceptions are Transient: a bounded retry (max_retries) is safer than giving up on
    something that may be a blip."""
    if isinstance(exc, CragError):
        return type(exc)
    from pydantic import ValidationError

    if isinstance(exc, ValidationError):
        return ParseError
    status = status_of(exc)
    if status is not None:
        if status in (408, 409, 425, 429) or status >= 500:
            return TransientError
        if 400 <= status < 500:
            return PermanentError
    if isinstance(exc, (ValueError, TypeError)) and any(
        t in str(exc).lower() for t in _PARSE_HINTS
    ):
        return ParseError
    return TransientError


def to_permanent(exc: BaseException) -> PermanentError:
    return PermanentError(f"{type(exc).__name__}: {exc}", status=status_of(exc))
