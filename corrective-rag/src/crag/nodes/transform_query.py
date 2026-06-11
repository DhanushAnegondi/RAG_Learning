"""transform_query node — rewrite the question for better web search (correction path, M4)."""
from __future__ import annotations

from ..llm import get_llm

REWRITE_PROMPT = (
    "The local documents did not answer this question well. Rewrite it as a concise, "
    "self-contained web-search query that would surface the answer. Return ONLY the rewritten "
    "query, no preamble.\n\nOriginal: {question}\nRewritten:"
)


def transform_query(state: dict) -> dict:
    resp = get_llm().invoke(REWRITE_PROMPT.format(question=state["question"]))
    rewritten = getattr(resp, "content", resp).strip()
    return {"question": rewritten, "steps": state.get("steps", []) + ["transform_query"]}
