"""The graph state: one dict threaded through every node.

`total=False` so nodes return PARTIAL updates that LangGraph merges. Each key has exactly one
writer and one meaning. In particular `question` is the user's original question and is never
rewritten: the rewrite node writes `search_query`, and generation answers `question`.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from langchain_core.documents import Document

from .retrieval import ScoredChunk

Verdict = Literal["correct", "ambiguous", "incorrect"]
Route = Literal["local", "local+web", "web", "abstain"]


class CRAGState(TypedDict, total=False):
    question: str  # original user question; written once, never overwritten
    search_query: str  # rewrite_query output, used only for web search
    chunks: list[ScoredChunk]  # local retrieval, rank order
    grades: list[bool]  # parallel to `chunks`; True = relevant
    web_chunks: list[Document]  # web results (url/title metadata)
    web_grades: list[bool]  # parallel to `web_chunks`
    verdict: Verdict  # three-way CRAG verdict from the local grades
    answer: str
    citations: list[dict[str, Any]]  # id, source, section, url, snippet
    context: list[dict[str, Any]]  # docs actually given to the generator, ids match [N]
    route: Route
    abstained: bool
    steps: list[str]  # ordered node trace
