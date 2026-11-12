"""Seeded fault injection around the provider boundary (chat, embeddings, web search).

Each provider call fails with probability `rate`; the fault kind is sampled from the kinds that make
sense for that channel. Faults are only active between `begin(qid)` and `end()`, so indexing and
judging are never disturbed. Each draw is keyed by (seed, question id, channel, call input,
occurrence index) - see `FaultInjector` - so a run is reproducible for a given code path and both
systems face the same fault *distribution*. Every provider attempt is also counted per channel.

Two modes share the same wrappers:
  * offline: fakes from `fakes.py` sit behind the wrappers (no key, deterministic).
  * live: the REAL ChatNVIDIA / NVIDIAEmbeddings / DDGS classes are patched at class level, so it
    works on v0 and v1 alike without either knowing.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import pkgutil
import random
import threading
from collections.abc import Callable, Iterator
from typing import Any

from . import fakes

CHAT_KINDS = ("timeout", "429", "500")
STRUCTURED_KINDS = (*CHAT_KINDS, "empty_structured")
EMBED_KINDS = ("embeddings_down", "timeout")
WEB_KINDS = ("web_down", "timeout")
CHANNEL_KINDS = {
    "chat": CHAT_KINDS,
    "structured": STRUCTURED_KINDS,
    "embed": EMBED_KINDS,
    "web": WEB_KINDS,
}


def exception_for(kind: str) -> Exception:
    """The exception a provider outage of this kind produces (messages mimic the real SDKs)."""
    return {
        "timeout": TimeoutError("request timed out"),
        "429": Exception("[429] Too Many Requests"),
        "500": Exception("[500] Internal Server Error"),
        "embeddings_down": ConnectionError("embeddings service unavailable"),
        "web_down": ConnectionError("web search unavailable"),
    }[kind]


def call_key(args: tuple[Any, ...]) -> str:
    """Stable identity of a provider call from its first argument (prompt, text, or query)."""
    first = args[0] if args else ""
    if isinstance(first, list) and all(isinstance(x, str) for x in first):
        text = "\n".join(first)  # a list of texts (embed_documents)
    elif isinstance(first, str):
        text = first
    else:
        text = fakes.flatten(first)
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:12]


class FaultInjector:
    """Decides, per provider call, whether to inject a fault; counts every call attempt.

    Determinism: the draw for a call is keyed by (seed, question id, channel, hash of the call's
    own input, occurrence index of that exact input within the question). Parallel grading threads
    send different chunks, so thread scheduling cannot change which faults fire. Identical repeated
    inputs (retries) get successive occurrence indexes. The only residual dependence is on the
    system's own control flow (a different path makes different calls)."""

    def __init__(self, rate: float, seed: int = 7):
        if not 0.0 <= rate <= 1.0:
            raise ValueError("rate must be in [0, 1]")
        self.rate, self.seed = rate, seed
        self.active = False
        self.qid = ""
        self.faults: list[tuple[str, str]] = []
        self.calls: dict[str, int] = dict.fromkeys(CHANNEL_KINDS, 0)
        self._seen: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def begin(self, qid: str) -> None:
        with self._lock:
            self.qid, self.active = qid, True
            self.faults, self._seen = [], {}
            self.calls = dict.fromkeys(CHANNEL_KINDS, 0)

    def end(self) -> list[tuple[str, str]]:
        with self._lock:
            self.active = False
            return list(self.faults)

    def draw(self, channel: str, key: str = "") -> str | None:
        """Count this provider attempt; return a fault kind or None."""
        with self._lock:
            if not self.active:
                return None
            self.calls[channel] += 1
            n = self._seen.get((channel, key), 0)
            self._seen[(channel, key)] = n + 1
            rng = random.Random(f"{self.seed}:{self.qid}:{channel}:{key}:{n}")
            if rng.random() >= self.rate:
                return None
            kind = rng.choice(CHANNEL_KINDS[channel])
            self.faults.append((channel, kind))
            return kind


class FaultyStructured:
    def __init__(self, inner: Any, inj: FaultInjector):
        self._inner, self._inj = inner, inj

    def invoke(self, *a: Any, **k: Any) -> Any:
        kind = self._inj.draw("structured", call_key(a))
        if kind == "empty_structured":
            return None
        if kind:
            raise exception_for(kind)
        return self._inner.invoke(*a, **k)


class FaultyChat:
    """Wraps any chat model exposing `.invoke` and `.with_structured_output`."""

    def __init__(self, inner: Any, inj: FaultInjector):
        self._inner, self._inj = inner, inj

    def invoke(self, *a: Any, **k: Any) -> Any:
        kind = self._inj.draw("chat", call_key(a))
        if kind:
            raise exception_for(kind)
        return self._inner.invoke(*a, **k)

    def with_structured_output(self, *a: Any, **k: Any) -> FaultyStructured:
        return FaultyStructured(self._inner.with_structured_output(*a, **k), self._inj)


class FaultyEmbeddings:
    def __init__(self, inner: Any, inj: FaultInjector):
        self._inner, self._inj = inner, inj

    def _gate(self, arg: Any) -> None:
        kind = self._inj.draw("embed", call_key((arg,)))
        if kind:
            raise exception_for(kind)

    def embed_query(self, text: str) -> list[float]:
        self._gate(text)
        return self._inner.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._gate(texts)
        return self._inner.embed_documents(texts)


# -- patching helpers ---------------------------------------------------------------------------

_MISSING = object()


@contextlib.contextmanager
def _patched(patches: list[tuple[Any, str, Any]]) -> Iterator[None]:
    """setattr each (obj, name, value); restore (or delete a newly-added attr) on exit."""
    saved = [(o, n, vars(o).get(n, _MISSING)) for o, n, _ in patches]
    try:
        for o, n, v in patches:
            setattr(o, n, v)
        yield
    finally:
        for o, n, old in reversed(saved):
            if old is _MISSING:
                with contextlib.suppress(AttributeError):
                    delattr(o, n)
            else:
                setattr(o, n, old)


def _ddgs_classes() -> list[Any]:
    """The REAL DDGS classes. `ddgs.DDGS` is a lazy proxy whose `__call__` builds `ddgs.ddgs.DDGS`,
    so patching the proxy would silently miss; import the concrete class first and dedupe."""
    out: list[Any] = []
    for mod in ("ddgs.ddgs", "ddgs", "duckduckgo_search"):
        with contextlib.suppress(Exception):
            cls = importlib.import_module(mod).DDGS
            if cls not in out and "text" in vars(cls):
                out.append(cls)
    return out


def node_modules() -> list[Any]:
    """Every `crag.nodes.*` submodule (v0 nodes import `get_llm` by name; each needs patching)."""
    pkg = importlib.import_module("crag.nodes")
    return [
        importlib.import_module(f"crag.nodes.{m.name}") for m in pkgutil.iter_modules(pkg.__path__)
    ]


def _web_patches(inj: FaultInjector, offline: bool) -> list[tuple[Any, str, Any]]:
    patches = []
    for cls in _ddgs_classes():
        real = cls.text

        def text(self: Any, query: str, *a: Any, _real: Callable = real, **k: Any) -> Any:
            kind = inj.draw("web", call_key((query,)))
            if kind:
                raise exception_for(kind)
            if offline:
                return fakes.fake_web_results(query, k.get("max_results", 4))
            return _real(self, query, *a, **k)

        patches.append((cls, "text", text))
    return patches


def _live_class_patches(inj: FaultInjector) -> list[tuple[Any, str, Any]]:
    """Wrap the real provider classes at class level (instance lookups then hit the wrapper)."""
    from langchain_nvidia_ai_endpoints import ChatNVIDIA, NVIDIAEmbeddings

    real_invoke = ChatNVIDIA.invoke
    real_struct = ChatNVIDIA.with_structured_output
    real_q, real_d = NVIDIAEmbeddings.embed_query, NVIDIAEmbeddings.embed_documents

    def invoke(self: Any, *a: Any, **k: Any) -> Any:
        kind = inj.draw("chat", call_key(a))
        if kind:
            raise exception_for(kind)
        return real_invoke(self, *a, **k)

    def with_structured_output(self: Any, *a: Any, **k: Any) -> Any:
        return FaultyStructured(real_struct(self, *a, **k), inj)

    def embed_query(self: Any, *a: Any, **k: Any) -> Any:
        kind = inj.draw("embed", call_key(a))
        if kind:
            raise exception_for(kind)
        return real_q(self, *a, **k)

    def embed_documents(self: Any, *a: Any, **k: Any) -> Any:
        kind = inj.draw("embed", call_key(a))
        if kind:
            raise exception_for(kind)
        return real_d(self, *a, **k)

    return [
        (ChatNVIDIA, "invoke", invoke),
        (ChatNVIDIA, "with_structured_output", with_structured_output),
        (NVIDIAEmbeddings, "embed_query", embed_query),
        (NVIDIAEmbeddings, "embed_documents", embed_documents),
    ]


@contextlib.contextmanager
def install(system: str, inj: FaultInjector, *, offline: bool) -> Iterator[None]:
    """Route chat/embeddings/web of `system` ('v0'|'v1') through the injector; undo on exit.

    The `crag` package of that system must already be importable (run.py arranges sys.path)."""
    patches = _web_patches(inj, offline)
    cleanup = contextlib.ExitStack()
    if not offline:
        patches += _live_class_patches(inj)
    elif system == "v0":
        import crag.ingest as ingest
        import crag.llm as llm

        def get_llm(**_k: Any) -> Any:
            return FaultyChat(fakes.FakeChat(), inj)

        def get_embeddings() -> Any:
            return FaultyEmbeddings(fakes.HashEmbeddings(), inj)

        patches += [
            (llm, "get_llm", get_llm),
            (llm, "get_embeddings", get_embeddings),
            (ingest, "get_embeddings", get_embeddings),
        ]
        patches += [(m, "get_llm", get_llm) for m in node_modules() if hasattr(m, "get_llm")]
    elif system == "v1":
        import crag.llm as llm

        llm.set_chat_factory(lambda model: FaultyChat(fakes.FakeChat(model), inj))
        llm.set_embeddings_factory(lambda: FaultyEmbeddings(fakes.HashEmbeddings(), inj))
        cleanup.callback(llm.reset_factories)
    else:
        raise ValueError(f"unknown system {system!r}")
    with cleanup, _patched(patches):
        yield
