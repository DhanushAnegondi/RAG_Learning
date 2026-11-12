"""rewrite_query node: turn the question into a web-search query.

Writes `search_query` ONLY. `question` stays the user's original so generation answers what was
asked (the v0 bug was a rewrite overwriting `question`). If rewriting fails, search with the
original question rather than failing the run.
"""

from __future__ import annotations

from ..llm import LLMClient
from ..observability import current_context
from ..state import CRAGState
from .web_search import web_blocked

REWRITE_SYSTEM = (
    "The local documents did not answer the user's question well. Rewrite it as one concise, "
    "self-contained web search query. Reply with ONLY the search query, no quotes, no preamble."
)


def rewrite_query(state: CRAGState, client: LLMClient) -> dict:
    question = state["question"]
    steps = [*state.get("steps", []), "rewrite_query"]
    query = ""
    if web_blocked():
        # The search will be skipped by the breaker: do not spend an LLM call on it.
        return {"search_query": question, "steps": steps}
    try:
        text = client.complete([("system", REWRITE_SYSTEM), ("user", question)], purpose="rewrite")
        lines = text.strip().splitlines()
        query = lines[0].strip().strip("\"'") if lines else ""
    except Exception as exc:
        ctx = current_context()
        if ctx is not None:
            ctx.record_error(f"rewrite failed, using original question: {type(exc).__name__}")
    return {"search_query": query or question, "steps": steps}
