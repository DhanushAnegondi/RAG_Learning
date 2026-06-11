"""Auto-suggest length/tone via a plain-text prompt + parse (mocked)."""
from copilot.suggest import StyleSuggestion, suggest_style


def test_suggest_parses_the_models_line(monkeypatch, fake_llm):
    monkeypatch.setattr(
        "copilot.suggest.chat", lambda *a, **k: fake_llm(text="length=short; tone=conversational")
    )
    out = suggest_style("Tell me about yourself")
    assert out.length == "short"
    assert out.tone == "conversational"


def test_suggest_recovers_from_loose_wording(monkeypatch, fake_llm):
    # model didn't use the exact format but mentioned valid words
    monkeypatch.setattr(
        "copilot.suggest.chat",
        lambda *a, **k: fake_llm(text="I'd go with a long, professional answer here."),
    )
    out = suggest_style("Walk me through the pipeline")
    assert out.length == "long"
    assert out.tone == "professional"


def test_suggest_falls_back_on_empty_output(monkeypatch, fake_llm):
    monkeypatch.setattr("copilot.suggest.chat", lambda *a, **k: fake_llm(text=""))
    out = suggest_style("anything")
    assert out.length == "medium" and out.tone == "professional"


def test_style_suggestion_schema():
    assert set(StyleSuggestion.model_fields) == {"length", "tone", "reason"}
