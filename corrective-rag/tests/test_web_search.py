"""web_search converts DDG hits into Documents with source URLs. Network is faked."""
from crag.nodes import web_search as ws_mod
from crag.nodes.web_search import web_search


class _FakeDDGS:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def text(self, _query, max_results=4):
        return [
            {"body": "b1", "href": "u1", "title": "t1"},
            {"body": "b2", "href": "u2", "title": "t2"},
        ]


def test_web_search_returns_documents(monkeypatch):
    monkeypatch.setattr(ws_mod, "_ddgs", lambda: _FakeDDGS)
    out = web_search({"question": "q"})
    assert len(out["web_results"]) == 2
    assert out["web_results"][0].metadata["source"] == "u1"
    assert "web_search" in out["steps"]
