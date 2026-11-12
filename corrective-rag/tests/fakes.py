"""Offline fakes shared by the v1 tests (kept out of conftest so they import explicitly)."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from langchain_core.embeddings import Embeddings

DIM = 128


class HashEmbeddings(Embeddings):
    """Deterministic hash bag-of-words embeddings; counts how many texts were embedded."""

    def __init__(self) -> None:
        self.embedded = 0
        self.fail = False

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * DIM
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIM] += 1.0
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise ConnectionError("embeddings down")
        self.embedded += len(texts)
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        if self.fail:
            raise ConnectionError("embeddings down")
        return self._vec(text)


class Reply:
    def __init__(self, content: str):
        self.content = content


class ScriptedChat:
    """Fake chat model. `script` outcomes are consumed per call: an Exception is raised, anything
    else is returned (str -> Reply, other -> as-is). `structured_script` serves
    `.with_structured_output(...).invoke`."""

    def __init__(self, model: str, script: list[Any], structured_script: list[Any] | None = None):
        self.model = model
        self.script = list(script)
        self.structured_script = list(structured_script or [])
        self.calls = 0
        self.structured_calls = 0
        self.last_messages: Any = None

    @staticmethod
    def _pop(script: list[Any]) -> Any:
        out = script.pop(0) if len(script) > 1 else script[0]
        if isinstance(out, Exception):
            raise out
        return out

    def invoke(self, messages: Any) -> Any:
        self.calls += 1
        self.last_messages = messages
        out = self._pop(self.script)
        return Reply(out) if isinstance(out, str) else out

    def with_structured_output(self, _schema: Any) -> Any:
        outer = self

        class _S:
            def invoke(self, _m: Any) -> Any:
                outer.structured_calls += 1
                return outer._pop(outer.structured_script)

        return _S()
