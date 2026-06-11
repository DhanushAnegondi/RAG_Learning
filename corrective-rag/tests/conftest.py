"""Shared fixtures + fakes. The whole suite runs WITHOUT a live NVIDIA_API_KEY: the LLM,
embeddings, vector store and web search are all faked here."""
from __future__ import annotations

import os
import sys

import pytest
from langchain_core.documents import Document

# Make `import crag` work even if pytest's pythonpath ini isn't picked up.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))


# --- Fakes -----------------------------------------------------------------

class _Resp:
    def __init__(self, content: str):
        self.content = content


class _FakeStructured:
    """Stands in for llm.with_structured_output(GradeDecision)."""

    def __init__(self, decisions):
        self._decisions = list(decisions)
        self._i = 0

    def invoke(self, _msg):
        from crag.nodes.grade import GradeDecision

        val = self._decisions[self._i % len(self._decisions)]
        self._i += 1
        return GradeDecision(relevant=val)


class FakeLLM:
    """Fake ChatNVIDIA. `decisions` drives the grader; `text` is the generate/rewrite output."""

    def __init__(self, decisions=(True,), text="FAKE ANSWER"):
        self.decisions = decisions
        self.text = text

    def with_structured_output(self, _schema):
        return _FakeStructured(self.decisions)

    def invoke(self, _prompt):
        return _Resp(self.text)


class FakeStore:
    def __init__(self, docs):
        self._docs = docs

    def similarity_search(self, _query, k=4):
        return self._docs[:k]


class FakeDDGS:
    def __init__(self, results=None):
        self._results = results or [
            {"body": "web answer body", "href": "http://example.com", "title": "Example"}
        ]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def text(self, _query, max_results=4):
        return self._results[:max_results]


# --- Fixtures --------------------------------------------------------------

@pytest.fixture
def doc():
    return lambda text, **meta: Document(page_content=text, metadata=meta)


@pytest.fixture
def fake_llm():
    return FakeLLM


@pytest.fixture
def patch_llm(monkeypatch):
    """Patch get_llm in every node module that imported it. Returns a setter."""

    def _apply(llm):
        for mod in ("grade", "generate", "transform_query"):
            monkeypatch.setattr(f"crag.nodes.{mod}.get_llm", lambda *a, **k: llm)
        return llm

    return _apply
