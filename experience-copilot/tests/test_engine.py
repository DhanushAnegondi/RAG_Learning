"""Grounding engine: reuses crag retrieve; grades in parallel or skips (fast). Mocked."""
from crag.nodes.grade import GradeDecision

from copilot import engine


class _Structured:
    def __init__(self, keep_marker):
        self.keep_marker = keep_marker

    def invoke(self, prompt):
        return GradeDecision(relevant=self.keep_marker in prompt)


class _GradeLLM:
    def __init__(self, keep_marker="KEEP"):
        self.keep_marker = keep_marker

    def with_structured_output(self, _schema):
        return _Structured(self.keep_marker)


def test_fast_mode_skips_grading(monkeypatch, doc):
    docs = [doc("KEEP A"), doc("noise"), doc("KEEP B")]
    monkeypatch.setattr(engine, "retrieve", lambda state: {"documents": docs})

    def _boom(*a, **k):
        raise AssertionError("grading model was called in fast mode")

    monkeypatch.setattr(engine, "chat", _boom)
    out = engine.ground("q", grade=False)
    assert out["graded"] is False
    assert out["n_relevant"] == 3 and out["covered"] is True
    assert "noise" in out["context"]  # fast mode keeps everything retrieved


def test_grading_filters_and_runs(monkeypatch, doc):
    docs = [doc("KEEP A"), doc("noise"), doc("KEEP B")]
    monkeypatch.setattr(engine, "retrieve", lambda state: {"documents": docs})
    monkeypatch.setattr(engine, "chat", lambda *a, **k: _GradeLLM("KEEP"))
    out = engine.ground("q", grade=True)
    assert out["graded"] is True
    assert out["n_relevant"] == 2
    assert "KEEP A" in out["context"] and "KEEP B" in out["context"]
    assert "noise" not in out["context"]


def test_grading_keeps_chunk_on_failure(monkeypatch, doc):
    # if the grader errors, the chunk is kept (safe default)
    monkeypatch.setattr(engine, "retrieve", lambda state: {"documents": [doc("x")]})

    class _BoomLLM:
        def with_structured_output(self, _s):
            class _S:
                def invoke(self, _p):
                    raise RuntimeError("model down")
            return _S()

    monkeypatch.setattr(engine, "chat", lambda *a, **k: _BoomLLM())
    out = engine.ground("q", grade=True)
    assert out["n_relevant"] == 1
