"""The core: persona-conditioned, length/tone-controlled answer generation (in YOUR voice).

This is what Experience Copilot adds on top of crag. The system prompt fuses your persona + writing
samples + the requested length/tone, and grounds strictly on the retrieved context so it cannot
fabricate experience.
"""
from __future__ import annotations

from .llm import chat

LENGTH_SPEC = {
    "short": "2-3 sentences (~60 words). Lead with the single most important point.",
    "medium": "one tight paragraph (~120 words).",
    "long": "~250 words, lightly structured: the situation, what you did, and the impact. Use specifics.",
}
TONE_SPEC = {
    "formal": "formal and precise; full sentences; no contractions.",
    "professional": "clear and professional; confident; concrete; minimal fluff.",
    "conversational": "relaxed and conversational; contractions are fine; sounds spoken.",
    "humanized": "warm, natural, first-person; sounds like a real person talking, not a press release; "
    "small informalities are welcome.",
}

DEFAULT_LENGTH = "medium"
DEFAULT_TONE = "humanized"


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except FileNotFoundError:
        return ""


def _resolve(length: str, tone: str) -> tuple[str, str]:
    if length not in LENGTH_SPEC:
        length = DEFAULT_LENGTH
    if tone not in TONE_SPEC:
        tone = DEFAULT_TONE
    return length, tone


def build_prompt(question, context, persona, style, length, tone, extra_notes=""):
    length, tone = _resolve(length, tone)
    system = (
        "You write in the FIRST PERSON as the candidate described below, imitating their voice from "
        "the writing samples. Answer ONLY from the candidate's context and notes; never invent "
        "facts, projects, numbers, or employers. If the context does not support an answer, say so "
        "briefly and honestly rather than making something up. Each context block may be prefixed "
        "with [Experience: <employer>] — attribute each fact to that employer and never blend "
        "different employers' work into one story.\n\n"
        f"# Candidate persona\n{persona or '(none provided)'}\n\n"
        f"# The candidate's writing style — imitate this voice\n{style or '(none provided)'}\n\n"
        f"# Length\n{LENGTH_SPEC[length]}\n"
        f"# Tone\n{TONE_SPEC[tone]}"
    )
    user = f"Question: {question}\n\n# Context from the candidate's documents\n{context or '(no grounding found)'}"
    if extra_notes:
        user += f"\n\n# Extra notes the candidate just provided\n{extra_notes}"
    user += "\n\nWrite the answer in the candidate's voice."
    return system, user


def generate_answer(
    question: str,
    context: str,
    *,
    length: str = DEFAULT_LENGTH,
    tone: str = DEFAULT_TONE,
    persona: str | None = None,
    style: str | None = None,
    extra_notes: str = "",
    model: str | None = None,
    stream: bool = False,
):
    """Generate the answer. Returns a str, or (if stream=True) a generator of text chunks."""
    from .config import get_settings

    s = get_settings()
    persona = persona if persona is not None else _read(s.persona_path)
    style = style if style is not None else _read(s.style_path)
    system, user = build_prompt(question, context, persona, style, length, tone, extra_notes)
    messages = [("system", system), ("human", user)]
    llm = chat(model)
    if stream:
        return (getattr(chunk, "content", "") for chunk in llm.stream(messages))
    resp = llm.invoke(messages)
    return getattr(resp, "content", resp)
