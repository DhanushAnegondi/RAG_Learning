"""web_search node — DuckDuckGo fallback (no API key). Correction path, M4.

Stop condition (HANDOFF M4 why): this node has no edge back to grade/decide. The graph runs
retrieve -> grade -> (correction) transform_query -> web_search -> generate -> END. The correction
path executes AT MOST ONCE per question, so it cannot loop or re-grade forever.
"""
from __future__ import annotations

from langchain_core.documents import Document

MAX_RESULTS = 4


def _ddgs():
    """Return a DDGS class. The package was renamed duckduckgo-search -> ddgs; support both."""
    try:
        from duckduckgo_search import DDGS  # duckduckgo-search>=6
    except ImportError:  # pragma: no cover - depends on which version is installed
        from ddgs import DDGS  # newer package name
    return DDGS


def web_search(state: dict) -> dict:
    DDGS = _ddgs()
    results: list[Document] = []
    with DDGS() as ddgs:
        for r in ddgs.text(state["question"], max_results=MAX_RESULTS):
            results.append(
                Document(
                    page_content=r.get("body", ""),
                    metadata={"source": r.get("href", ""), "title": r.get("title", "")},
                )
            )
    return {"web_results": results, "steps": state.get("steps", []) + ["web_search"]}
