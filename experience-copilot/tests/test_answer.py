"""The voice/length/tone generator — the new concept."""
from copilot.answer import build_prompt, generate_answer


def test_prompt_encodes_length_tone_persona_and_context():
    system, user = build_prompt(
        question="What did you build?",
        context="Built a Snowflake pipeline.",
        persona="I am a data engineer.",
        style="I write plainly.",
        length="short",
        tone="formal",
    )
    assert "60 words" in system            # short length spec
    assert "no contractions" in system     # formal tone spec
    assert "I am a data engineer." in system
    assert "I write plainly." in system
    assert "Built a Snowflake pipeline." in user
    assert "What did you build?" in user


def test_auto_or_unknown_values_fall_back_to_defaults():
    system, _ = build_prompt("q", "c", "p", "s", length="auto", tone="auto")
    assert "120 words" in system           # default medium
    assert "warm, natural" in system       # default humanized


def test_extra_notes_are_included():
    _, user = build_prompt("q", "", "p", "s", "medium", "humanized", extra_notes="led a team of 4")
    assert "led a team of 4" in user


def test_generate_answer_uses_the_llm(monkeypatch, fake_llm):
    monkeypatch.setattr("copilot.answer.chat", lambda *a, **k: fake_llm(text="MY VOICE ANSWER"))
    out = generate_answer("q", "context", length="short", tone="formal", persona="P", style="S")
    assert out == "MY VOICE ANSWER"


def test_generate_answer_streams(monkeypatch, fake_llm):
    monkeypatch.setattr("copilot.answer.chat", lambda *a, **k: fake_llm(text="streamed answer here"))
    chunks = list(generate_answer("q", "c", persona="P", style="S", stream=True))
    assert "".join(chunks).strip() == "streamed answer here"
