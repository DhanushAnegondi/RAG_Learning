"""generate must answer from ONLY the surviving (relevant) context + web results."""
from crag.nodes.generate import _format_context, generate


def test_format_context_keeps_only_relevant(doc):
    state = {
        "documents": [doc("keep1"), doc("drop"), doc("keep2")],
        "grades": [True, False, True],
        "web_results": [],
    }
    ctx = _format_context(state)
    assert "keep1" in ctx and "keep2" in ctx and "drop" not in ctx


def test_format_context_includes_web_results(doc):
    state = {"documents": [], "grades": [], "web_results": [doc("from web")]}
    assert "from web" in _format_context(state)


def test_generate_returns_text(patch_llm, fake_llm, doc):
    patch_llm(fake_llm(text="THE ANSWER"))
    out = generate({"question": "q", "documents": [doc("x")], "grades": [True]})
    assert out["generation"] == "THE ANSWER"
    assert "generate" in out["steps"]
