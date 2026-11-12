"""Offline fakes for tests and `--offline` eval runs, installed at crag's provider seams."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Any

from crag.llm import set_chat_factory, set_embeddings_factory
from langchain_core.embeddings import Embeddings
from pydantic import BaseModel

DIM = 128


class HashEmbeddings(Embeddings):
    """Deterministic hashed bag-of-words embeddings (cosine-friendly, no network)."""

    def __init__(self) -> None:
        self.embedded = 0

    @staticmethod
    def _vec(text: str) -> list[float]:
        v = [0.0] * DIM
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIM] += 1.0
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embedded += len(texts)
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class Reply:
    def __init__(self, content: str):
        self.content = content


# handler(model, messages, schema) -> str | BaseModel | Exception; schema is None for plain calls
Handler = Callable[[str, Any, "type[BaseModel] | None"], Any]


class FakeChat:
    def __init__(self, model: str, handler: Handler):
        self.model = model
        self.handler = handler

    def invoke(self, messages: Any) -> Reply:
        out = self.handler(self.model, messages, None)
        if isinstance(out, Exception):
            raise out
        return Reply(out if isinstance(out, str) else str(out))

    def with_structured_output(self, schema: Any) -> Any:
        chat = self

        class _S:
            def invoke(self, messages: Any) -> Any:
                out = chat.handler(chat.model, messages, schema)
                if isinstance(out, Exception):
                    raise out
                return out

        return _S()


def install(handler: Handler, embeddings: Embeddings | None = None) -> HashEmbeddings | Embeddings:
    """Route crag's chat/embeddings factories to fakes; call `reset_factories()` afterwards."""
    emb = embeddings or HashEmbeddings()
    set_chat_factory(lambda model: FakeChat(model, handler))
    set_embeddings_factory(lambda: emb)
    return emb


def _text(messages: Any) -> str:
    if isinstance(messages, str):
        return messages
    parts = [m[1] if isinstance(m, tuple) else getattr(m, "content", m) for m in messages]
    return "\n".join(str(p) for p in parts)


def stub_handler(model: str, messages: Any, schema: Any) -> Any:
    """Offline eval stand-in for the live models.

    Grader: relevant iff the chunk shares a specific term with the question or names its
    employer. Generator: writes a
    mid-band answer naming the first context label. Because the generator is a stub, offline
    attribution/length numbers only prove the plumbing; they say nothing about model quality."""
    from copilot.engine import lexical_hits

    text = _text(messages)
    if schema is not None:  # grader
        q = re.search(r"Question: (.*)", text)
        doc = re.search(r"<doc>\n(.*?)\n</doc>", text, re.S)
        label = re.search(r"\[Experience: ([^\]]+)\]", doc.group(1)) if doc else None
        named = bool(q and label and label.group(1).lower() in q.group(1).lower())
        rel = bool(q and doc and (lexical_hits(q.group(1), doc.group(1)) >= 1 or named))
        return schema(relevant=rel)
    band = re.search(r"Hard requirement: (\d+)-(\d+) words", text)
    n = (int(band.group(1)) + int(band.group(2))) // 2 if band else 100
    label = re.search(r"\[Experience: ([^\]]+)\]", text)
    head = f"At {label.group(1)} I worked on this." if label else "My documents do not cover this."
    words = head.split()
    return " ".join(words + ["detail"] * max(0, n - len(words)))
