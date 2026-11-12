"""Auto-suggest a sensible length + tone from the question (the user can override).

Plain-text prompt + keyword parse rather than structured output: on a 30B reasoning model the
multi-field enum schema returned None too often. The call goes through crag's `LLMClient`; on any
failure or an empty reply a deterministic keyword heuristic answers instead, so it never fails.
"""
from __future__ import annotations

import re
from typing import Literal

from crag.llm import LLMClient
from pydantic import BaseModel, Field

from .config import Settings, get_settings

LENGTHS = ("short", "medium", "long")
TONES = ("formal", "professional", "conversational", "humanized")


class StyleSuggestion(BaseModel):
    length: Literal["short", "medium", "long"] = Field(description="Suggested answer length.")
    tone: Literal["formal", "professional", "conversational", "humanized"] = Field(
        description="Suggested tone."
    )
    reason: str = Field(description="One short clause explaining the choice.")


_PROMPT = (
    "You help someone answer questions about their own experience. For the question below, choose "
    "an answer LENGTH and TONE.\n"
    "LENGTH must be one of: short, medium, long.\n"
    "TONE must be one of: formal, professional, conversational, humanized.\n"
    "Guidance: quick rapport questions ('tell me about yourself') lean short/medium + "
    "conversational or humanized; deep technical questions ('walk me through the pipeline') lean "
    "medium/long + professional.\n"
    "Reply with EXACTLY one line, nothing else, in this format:\n"
    "length=<value>; tone=<value>\n\n"
    "Question: {question}"
)

_TECHNICAL = re.compile(
    r"pipeline|architect|design|walk me through|how did you|optimi[sz]|scal|migrat|debug|"
    r"trade-?off|implement|schema|latency|cost",
    re.I,
)
_RAPPORT = re.compile(
    r"yourself|introduce|why (this|our|us)|strength|weakness|hobby|motivat|passion|fit", re.I
)


def heuristic_style(question: str) -> StyleSuggestion:
    """Keyword fallback (no LLM): technical -> long/professional, rapport -> short/humanized."""
    if _TECHNICAL.search(question):
        return StyleSuggestion(length="long", tone="professional", reason="heuristic: technical")
    if _RAPPORT.search(question):
        return StyleSuggestion(length="short", tone="humanized", reason="heuristic: rapport")
    return StyleSuggestion(length="medium", tone="professional", reason="heuristic: default")


def _pick(text: str, key: str, allowed: tuple[str, ...]) -> str | None:
    low = text.lower()
    m = re.search(rf"{key}\s*[=:]\s*([a-z]+)", low)
    if m and m.group(1) in allowed:
        return m.group(1)
    for word in allowed:  # fallback: any allowed word from this category in the reply
        if re.search(rf"\b{word}\b", low):
            return word
    return None


def suggest_style(
    question: str,
    *,
    settings: Settings | None = None,
    client: LLMClient | None = None,
    model: str | None = None,
) -> StyleSuggestion:
    s = settings or get_settings()
    fallback = heuristic_style(question)
    try:
        client = client or LLMClient(s.to_crag_settings())
        text = client.complete(
            [("user", _PROMPT.format(question=question))],
            purpose="suggest",
            model=model or s.grader_model,
        )
    except Exception:  # any provider fault: use the heuristic
        return fallback
    length = _pick(text, "length", LENGTHS)
    tone = _pick(text, "tone", TONES)
    if length is None and tone is None:
        return fallback
    return StyleSuggestion(
        length=length or fallback.length,  # type: ignore[arg-type]
        tone=tone or fallback.tone,  # type: ignore[arg-type]
        reason=text.strip().splitlines()[0][:100],
    )
