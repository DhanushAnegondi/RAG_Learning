"""LLMClient: the only place in crag that talks to ChatNVIDIA / NVIDIAEmbeddings.

Why one choke point: retries, timeouts, model fallback and per-call telemetry are cross-cutting.
Putting them here keeps nodes free of try/except noise, and gives tests a single seam
(`set_chat_factory` / `set_embeddings_factory`) to fake the provider.

Failure policy (see errors.py for the taxonomy):
  * TransientError  -> exponential backoff + jitter, up to `max_retries`, then next model in chain.
  * PermanentError  -> never retried. If model-specific (404) try the next model, else raise.
  * ParseError      -> structured output only: one plain-text retry asking for JSON, then raise.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel
from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from .config import Settings, get_settings
from .errors import (
    CragError,
    ParseError,
    PermanentError,
    TransientError,
    classify,
    status_of,
)
from .observability import LLMCall, current_context, redact

ChatFactory = Callable[[str], Any]
EmbeddingsFactory = Callable[[], Any]

_chat_factory: ChatFactory | None = None
_embeddings_factory: EmbeddingsFactory | None = None


def set_chat_factory(fn: ChatFactory) -> None:
    """Test seam: `fn(model_name)` must return an object with `.invoke(messages)` (returning
    something with `.content`) and `.with_structured_output(schema)`."""
    global _chat_factory
    _chat_factory = fn


def set_embeddings_factory(fn: EmbeddingsFactory) -> None:
    """Test seam: `fn()` returns a LangChain-style Embeddings object."""
    global _embeddings_factory
    _embeddings_factory = fn


def reset_factories() -> None:
    global _chat_factory, _embeddings_factory
    _chat_factory = None
    _embeddings_factory = None


def _require_key(settings: Settings) -> str:
    if not settings.key_configured:
        raise PermanentError("NVIDIA_API_KEY is not configured", status=401)
    assert settings.nvidia_api_key is not None
    return settings.nvidia_api_key.get_secret_value()


def _default_chat(model: str, settings: Settings | None = None) -> Any:
    from langchain_nvidia_ai_endpoints import ChatNVIDIA

    s = settings or get_settings()
    # max_tokens covers reasoning tokens too: at the SDK default (1024) a reasoning model can spend
    # all of it thinking and return empty content with finish_reason "length".
    return ChatNVIDIA(
        model=model, temperature=0, max_tokens=s.llm_max_tokens, api_key=_require_key(s)
    )


def _default_embeddings() -> Any:
    from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings

    s = get_settings()
    # truncate="END" avoids hard errors on chunks longer than the model max.
    return NVIDIAEmbeddings(model=s.embed_model, truncate="END", api_key=_require_key(s))


def get_embeddings() -> Any:
    """Embeddings object (factory-aware). Used by the indexer and the dense retriever."""
    return (_embeddings_factory or _default_embeddings)()


def get_llm(**_kwargs: Any) -> Any:
    """v0-compatible raw chat model for `settings.llm_model` (old nodes call this)."""
    return (_chat_factory or _default_chat)(get_settings().llm_model)


def _content(resp: Any) -> str:
    c = getattr(resp, "content", resp)
    return c if isinstance(c, str) else str(c or "")


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _extract_json(text: str) -> str:
    """Pull a JSON object out of a plain-text reply (strips code fences / chatter)."""
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ParseError("no JSON object in model reply")
    return text[start : end + 1]


class BudgetExceeded(TransientError):
    """The per-call total time budget is spent: stop retrying and stop falling back."""


class LLMClient:
    """Resilient chat client. `sleep` is injectable so tests never actually wait."""

    def __init__(
        self, settings: Settings | None = None, *, sleep: Callable[[float], None] = time.sleep
    ):
        self.settings = settings or get_settings()
        self._sleep = sleep
        self._chats: dict[str, Any] = {}

    # -- public API ---------------------------------------------------------------------------

    def complete(self, messages: Sequence[Any], *, purpose: str, model: str | None = None) -> str:
        """Plain-text completion. Raises a CragError only if every model in the chain failed."""

        def run(chat: Any, _model: str) -> str:
            text = _content(self._invoke(chat.invoke, messages))
            if not text.strip():
                raise TransientError("empty completion")
            return text

        return self._run_chain(purpose, model, run)

    def structured(
        self,
        messages: Sequence[Any],
        schema: type[BaseModel],
        *,
        purpose: str,
        model: str | None = None,
    ) -> BaseModel:
        """Structured output validated against `schema`.

        Native structured output first; on ParseError (None / invalid) one plain-text retry that
        asks for JSON and parses it ourselves. Raises ParseError if that also fails."""

        def run(chat: Any, _model: str) -> BaseModel:
            try:
                runnable = chat.with_structured_output(schema)
            except Exception:  # e.g. NotImplementedError: no native structured output
                runnable = None
            if runnable is not None:
                try:
                    return self._coerce(self._invoke(runnable.invoke, messages), schema)
                except ParseError:
                    pass
            hint = (
                "Reply with ONLY a JSON object matching this JSON schema, no prose:\n"
                + json.dumps(schema.model_json_schema())
            )
            text = _content(self._invoke(chat.invoke, [*messages, ("user", hint)]))
            try:
                return schema.model_validate_json(_extract_json(text))
            except ValueError as exc:  # ValidationError subclasses ValueError
                raise ParseError(f"plain-text fallback unparseable: {exc}") from exc

        return self._run_chain(purpose, model, run)

    # -- internals ----------------------------------------------------------------------------

    @staticmethod
    def _coerce(out: Any, schema: type[BaseModel]) -> BaseModel:
        if out is None:
            raise ParseError("structured output was None")
        if isinstance(out, schema):
            return out
        try:
            return schema.model_validate(out)
        except ValueError as exc:
            raise ParseError(f"structured output invalid: {exc}") from exc

    def _chat(self, model: str) -> Any:
        if model not in self._chats:
            try:
                if _chat_factory is not None:
                    self._chats[model] = _chat_factory(model)
                else:
                    self._chats[model] = _default_chat(model, self.settings)
            except CragError:
                raise
            except Exception as exc:  # SDK construction errors (bad model id, missing key)
                raise self._wrap(exc) from exc
        return self._chats[model]

    def _invoke(self, fn: Callable[..., Any], *args: Any) -> Any:
        """One provider call with a hard timeout; any raw exception becomes a typed CragError.

        Runs in a daemon thread so a hung call can never block interpreter exit."""
        box: dict[str, Any] = {}

        def target() -> None:
            try:
                box["value"] = fn(*args)
            except BaseException as exc:  # re-raised below, typed
                box["error"] = exc

        t = threading.Thread(target=target, daemon=True)
        t.start()
        t.join(self.settings.llm_timeout_s)
        if t.is_alive():
            raise TransientError(f"timeout after {self.settings.llm_timeout_s}s")
        exc = box.get("error")
        if exc is None:
            return box.get("value")
        if isinstance(exc, CragError) or not isinstance(exc, Exception):
            raise exc
        raise self._wrap(exc) from exc

    @staticmethod
    def _wrap(exc: Exception) -> CragError:
        kind = classify(exc)
        msg = redact(f"{type(exc).__name__}: {exc}")[:500]
        if kind is PermanentError:
            return PermanentError(msg, status=status_of(exc))
        return kind(msg)

    def _chain(self, model: str | None) -> list[str]:
        first = model or self.settings.llm_model
        return [first] + [m for m in self.settings.fallback_models if m != first]

    def _run_chain(self, purpose: str, model: str | None, run: Callable[[Any, str], Any]) -> Any:
        start = time.perf_counter()
        deadline = start + self.settings.llm_total_budget_s
        retries = 0
        last: CragError | None = None
        chain = self._chain(model)

        def on_retry(_state: Any) -> None:
            nonlocal retries
            retries += 1

        def record(used: str, idx: int, err: str | None) -> None:
            ctx = current_context()
            if ctx is None:
                return
            ctx.record_llm_call(
                LLMCall(
                    purpose=purpose,
                    model=used,
                    latency_ms=round((time.perf_counter() - start) * 1000.0, 1),
                    retries=retries,
                    fallback_used=idx > 0,
                    error=err,
                )
            )
            if err:
                ctx.record_error(f"llm[{purpose}] {err}")

        def attempt(n: str) -> Any:
            if time.perf_counter() >= deadline:
                raise BudgetExceeded(f"total budget {self.settings.llm_total_budget_s}s spent")
            return run(self._chat(n), n)

        for idx, name in enumerate(chain):
            base = self.settings.backoff_base_s
            retrying = Retrying(
                retry=retry_if_exception(
                    lambda e: isinstance(e, TransientError) and not isinstance(e, BudgetExceeded)
                ),
                stop=stop_after_attempt(self.settings.max_retries + 1),
                wait=wait_exponential(multiplier=base, max=8.0) + wait_random(0, base),
                sleep=self._sleep,
                before_sleep=on_retry,
                reraise=True,
            )
            try:
                result = retrying(lambda n=name: attempt(n))
                record(name, idx, None)
                return result
            except ParseError as exc:
                record(name, idx, f"ParseError: {exc}")
                raise
            except PermanentError as exc:
                last = exc
                if not exc.model_specific:
                    record(name, idx, f"PermanentError: {exc}")
                    raise
            except BudgetExceeded as exc:
                record(name, idx, f"BudgetExceeded: {exc}")
                raise
            except TransientError as exc:
                last = exc
        assert last is not None
        record(chain[-1], len(chain) - 1, f"{type(last).__name__}: {last}")
        raise last


__all__ = [
    "LLMClient",
    "get_embeddings",
    "get_llm",
    "reset_factories",
    "set_chat_factory",
    "set_embeddings_factory",
]
