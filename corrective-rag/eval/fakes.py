"""Offline stand-ins for the provider (chat, embeddings, web). Deterministic, no key, no network.

They exist to measure ROBUSTNESS (does the pipeline survive faults?), not answer quality: the
"grader" is a keyword-overlap heuristic and the "generator" echoes the first context sentence.
Both systems get the same fakes, so the comparison is fair.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from langchain_core.embeddings import Embeddings

DIM = 128
GRADE_OVERLAP = 3  # distinct shared content words needed to call a chunk "relevant"
DONT_KNOW = "I don't know based on the provided context."
_STOP = frozenset(
    "the a an of to is are was were for and or in on at by with what which who how when does do "
    "it its this that be as from can must should there their any not no per".split()
)
_TOK = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> set[str]:
    return {t for t in _TOK.findall(text.lower()) if len(t) > 2 and t not in _STOP}


class HashEmbeddings(Embeddings):
    """Deterministic hashed bag-of-words vectors."""

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * DIM
        for tok in _TOK.findall(text.lower()):
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIM] += 1.0
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class Reply:
    def __init__(self, content: str):
        self.content = content


def flatten(messages: Any) -> str:
    """Prompt text from a str, a list of (role, text) tuples, or LangChain message objects."""
    if isinstance(messages, str):
        return messages
    parts = []
    for m in messages:
        if isinstance(m, tuple):
            parts.append(str(m[1]))
        else:
            parts.append(str(getattr(m, "content", m)))
    return "\n".join(parts)


def _between(text: str, start: str, ends: tuple[str, ...]) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    body = text[i + len(start) :]
    cut = min((body.find(e) for e in ends if body.find(e) >= 0), default=len(body))
    return body[:cut].strip()


def _first_sentence(context: str) -> str:
    for line in context.splitlines():
        if line.lstrip().startswith("<doc") or line.strip() == "</doc>":
            continue
        line = re.sub(r"^[#>*\-\s\d.\[\]]+", "", line.strip())
        if len(line) > 15 and set(line) != {"-"}:
            return re.split(r"(?<=[.!?])\s", line)[0]
    return ""


class FakeChat:
    """Chat model that recognises the three prompt kinds by their wording."""

    def __init__(self, model: str = "fake"):
        self.model = model

    @staticmethod
    def kind(text: str) -> str:
        low = text.lower()
        if "<doc>" in low or ("document:" in low and "relevant" in low):
            return "grade"  # v1 wraps the graded chunk in <doc>, v0 uses "Document:"
        if "rewrite" in low and ("search query" in low or "rewritten" in low):
            return "rewrite"
        return "generate"

    @staticmethod
    def _question(text: str) -> str:
        q = _between(text, "Question:", ("\n",)) or _between(text, "Original:", ("\n",))
        if q:
            return q
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return lines[-1].strip() if lines else ""  # v1 rewrite: the question is the user turn

    def _grade(self, text: str) -> bool:
        q = self._question(text)
        doc = _between(text, "<doc>", ("</doc>",)) or _between(
            text, "Document:", ("Is this document", "\n\nQuestion")
        )
        return len(tokens(q) & tokens(doc)) >= GRADE_OVERLAP

    def invoke(self, messages: Any, *_a: Any, **_k: Any) -> Reply:
        text = flatten(messages)
        kind = self.kind(text)
        if kind == "grade":  # plain-text JSON fallback path of a resilient client
            return Reply(json.dumps({"relevant": self._grade(text)}))
        if kind == "rewrite":
            return Reply(self._question(text) or "query")
        ctx = _between(text, "Context:", ("\nAnswer:", "\n\nAnswer")) or _between(
            text, "Documents:", ()
        )
        sent = _first_sentence(ctx)
        return Reply(f"{sent} [1]" if sent and ctx != "(no context)" else DONT_KNOW)

    def with_structured_output(self, schema: Any, *_a: Any, **_k: Any) -> Any:
        outer = self

        class _Structured:
            def invoke(self, messages: Any, *_a2: Any, **_k2: Any) -> Any:
                text = flatten(messages)
                return schema(**{f: outer._grade(text) for f in _bool_fields(schema)})

        return _Structured()


def _bool_fields(schema: Any) -> list[str]:
    fields = getattr(schema, "model_fields", {})
    return [n for n, f in fields.items() if f.annotation is bool] or ["relevant"]


def fake_web_results(query: str, max_results: int = 4) -> list[dict]:
    """Canned DuckDuckGo-shaped results (the offline run cannot judge web answer correctness)."""
    return [
        {
            "title": "Offline fake result",
            "href": "https://example.invalid/offline",
            "body": f"Offline snippet about {query}. No live web access in offline mode.",
        }
    ][:max_results]
