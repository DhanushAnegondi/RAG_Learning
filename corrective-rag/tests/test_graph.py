"""End-to-end graph wiring, fully mocked. Proves decide() routes both paths correctly."""
from langchain_core.documents import Document

from crag.graph import build_graph
from crag.nodes import retrieve as retrieve_mod
from crag.nodes import web_search as ws_mod


class _FakeStore:
    def __init__(self, docs):
        self._docs = docs

    def similarity_search(self, _query, k=4):
        return self._docs[:k]


class _FakeDDGS:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def text(self, _query, max_results=4):
        return [{"body": "web", "href": "u", "title": "t"}]


def _docs(n):
    return [Document(page_content=f"doc{i}", metadata={"source": str(i)}) for i in range(n)]


def test_good_path_routes_straight_to_generate(monkeypatch, patch_llm, fake_llm):
    monkeypatch.setattr(retrieve_mod, "get_vectorstore", lambda: _FakeStore(_docs(3)))
    patch_llm(fake_llm(decisions=[True, True, True], text="GOOD ANSWER"))
    result = build_graph().invoke({"question": "q", "steps": []})
    assert result["steps"] == ["retrieve", "grade", "generate"]
    assert result["generation"] == "GOOD ANSWER"


def test_bad_path_takes_correction_once(monkeypatch, patch_llm, fake_llm):
    monkeypatch.setattr(retrieve_mod, "get_vectorstore", lambda: _FakeStore(_docs(3)))
    monkeypatch.setattr(ws_mod, "_ddgs", lambda: _FakeDDGS)
    patch_llm(fake_llm(decisions=[False, False, False], text="WEB ANSWER"))
    result = build_graph().invoke({"question": "q", "steps": []})
    # correction path runs exactly once: no node visited twice (stop condition)
    assert result["steps"] == ["retrieve", "grade", "transform_query", "web_search", "generate"]
    assert result["generation"] == "WEB ANSWER"
