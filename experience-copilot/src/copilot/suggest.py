"""Auto-suggest a sensible length + tone from the question (user can override in the UI).

Uses a plain-text prompt + parse rather than structured output: on meta/llama-3.3-70b-instruct,
with_structured_output for this multi-field/enum schema returned None too often. A keyword parse with
a heuristic fallback is far more reliable here.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from .llm import FAST_MODEL, chat

LENGTHS = ("short", "medium", "long")
TONES = ("formal", "professional", "conversational", "humanized")


class StyleSuggestion(BaseModel):
    length: Literal["short", "medium", "long"] = Field(description="Suggested answer length.")
    tone: Literal["formal", "professional", "conversational", "humanized"] = Field(
        description="Suggested tone."
    )
    reason: str = Field(description="One short clause explaining the choice.")


DEFAULT_SUGGESTION = StyleSuggestion(length="medium", tone="professional", reason="default")

_PROMPT = (
    "You help someone answer questions about their own experience. For the question below, choose an "
    "answer LENGTH and TONE.\n"
    "LENGTH must be one of: short, medium, long.\n"
    "TONE must be one of: formal, professional, conversational, humanized.\n"
    "Guidance: quick rapport questions ('tell me about yourself') lean short/medium + "
    "conversational or humanized; deep technical questions ('walk me through the pipeline') lean "
    "medium/long + professional.\n"
    "Reply with EXACTLY one line, nothing else, in this format:\n"
    "length=<value>; tone=<value>\n\n"
    "Question: {question}"
)


def _pick(text: str, key: str, allowed: tuple[str, ...], default: str) -> str:
    low = text.lower()
    m = re.search(rf"{key}\s*[=:]\s*([a-z]+)", low)
    if m and m.group(1) in allowed:
        return m.group(1)
    for word in allowed:  # fallback: any allowed word from this category present in the reply
        if re.search(rf"\b{word}\b", low):
            return word
    return default


def suggest_style(question: str, model: str | None = None) -> StyleSuggestion:
    try:
        resp = chat(model or FAST_MODEL).invoke(_PROMPT.format(question=question))
        text = getattr(resp, "content", "") or ""
    except Exception:
        return DEFAULT_SUGGESTION
    if not text.strip():
        return DEFAULT_SUGGESTION
    length = _pick(text, "length", LENGTHS, "medium")
    tone = _pick(text, "tone", TONES, "professional")
    return StyleSuggestion(length=length, tone=tone, reason=text.strip().splitlines()[0][:100])
