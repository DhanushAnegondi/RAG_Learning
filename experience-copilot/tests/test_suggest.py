"""Auto-suggest via LLMClient with a heuristic fallback."""
from copilot.suggest import StyleSuggestion, heuristic_style, suggest_style
from eval.fakes import install


def test_suggest_parses_the_models_line(settings, client_for):
    install(lambda m, msgs, s: "length=short; tone=conversational")
    out = suggest_style("Tell me about yourself", settings=settings, client=client_for(settings))
    assert (out.length, out.tone) == ("short", "conversational")


def test_suggest_uses_the_grader_model_by_default(settings, client_for):
    seen = []
    install(lambda m, msgs, s: seen.append(m) or "length=medium; tone=formal")
    suggest_style("q", settings=settings, client=client_for(settings))
    assert seen == [settings.grader_model]


def test_suggest_recovers_from_loose_wording(settings, client_for):
    install(lambda m, msgs, s: "I'd go with a long, professional answer here.")
    out = suggest_style("Walk me through it", settings=settings, client=client_for(settings))
    assert (out.length, out.tone) == ("long", "professional")


def test_suggest_falls_back_to_heuristic_on_provider_failure(settings, client_for):
    install(lambda m, msgs, s: RuntimeError("provider down"))
    out = suggest_style(
        "Walk me through the pipeline design", settings=settings, client=client_for(settings)
    )
    assert out.reason.startswith("heuristic") and out.length == "long"


def test_suggest_falls_back_on_unusable_reply(settings, client_for):
    install(lambda m, msgs, s: "no idea, sorry")
    out = suggest_style("Tell me about yourself", settings=settings, client=client_for(settings))
    assert out.reason.startswith("heuristic") and out.length == "short"


def test_heuristic_default_and_schema():
    assert heuristic_style("Something else entirely").length == "medium"
    assert set(StyleSuggestion.model_fields) == {"length", "tone", "reason"}
