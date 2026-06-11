"""Shared fakes/fixtures. Suite runs offline (LLM mocked) but needs the `crag` package importable,
so we add both this project's src and ../corrective-rag/src to the path."""
from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "src")))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "corrective-rag", "src")))


class _Resp:
    def __init__(self, content):
        self.content = content


class _FakeStructured:
    def __init__(self, value):
        self.value = value

    def invoke(self, _msg):
        return self.value


class FakeLLM:
    """Fake ChatNVIDIA: `text` for generation, `suggestion` for with_structured_output."""

    def __init__(self, text="FAKE ANSWER", suggestion=None):
        self.text = text
        self.suggestion = suggestion

    def invoke(self, _messages):
        return _Resp(self.text)

    def stream(self, _messages):
        for word in self.text.split(" "):
            yield _Resp(word + " ")

    def with_structured_output(self, _schema):
        return _FakeStructured(self.suggestion)


@pytest.fixture
def fake_llm():
    return FakeLLM


@pytest.fixture
def doc():
    from langchain_core.documents import Document

    return lambda text, **meta: Document(page_content=text, metadata=meta)
