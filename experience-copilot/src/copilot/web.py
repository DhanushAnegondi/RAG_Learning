"""Opt-in web research via crag's `web_search` (DuckDuckGo, timeout + circuit breaker).

Never automatic: for personal-experience answers random web text must not leak into "your" answer.
Web text is untrusted: each result is wrapped in a `<web id=N source=URL>` block with any closing
`</doc`/`</web` tag neutralised, so a page cannot close its block and smuggle in instructions. The
caller passes `context` to `generate_answer(web_context=...)`, which labels it as not from the
knowledge base, tells the model to treat it as data, and adds a warning to the result.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from crag.guardrails import escape_doc_text
from crag.nodes.web_search import web_search
from crag.observability import run_context

from .config import Settings, get_settings

_WEB_CLOSER = re.compile(r"<\s*/\s*web", re.I)


def escape_web_tags(text: str) -> str:
    """Neutralise closing `</web` and `</doc` tags in untrusted text (idempotent)."""
    return _WEB_CLOSER.sub("<\\/web", escape_doc_text(text))


def _attr(value: object) -> str:
    return str(value or "").replace('"', "'").replace("\n", " ")[:200]


def format_web(docs: list) -> str:
    """Number web results from 1 and wrap each in a `<web>` block."""
    return "\n\n".join(
        f'<web id="{i}" source="{_attr(d.metadata.get("url"))}">\n'
        f"{escape_web_tags(d.page_content)}\n</web>"
        for i, d in enumerate(docs, start=1)
    )


@dataclass
class WebResearch:
    context: str = ""
    sources: list[dict[str, str]] = field(default_factory=list)  # {"title", "url"}
    degraded: bool = False
    errors: list[str] = field(default_factory=list)


def research_web(question: str, settings: Settings | None = None) -> WebResearch:
    s = settings or get_settings()
    with run_context() as ctx:
        out = web_search({"question": question, "steps": []}, s.to_crag_settings())
        docs = out.get("web_chunks", [])
        return WebResearch(
            context=format_web(docs),
            sources=[
                {"title": str(d.metadata.get("title", "")), "url": str(d.metadata.get("url", ""))}
                for d in docs
            ],
            degraded=ctx.degraded,
            errors=list(ctx.errors),
        )
