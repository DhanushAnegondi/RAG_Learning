r"""The CRAG graph: nodes + the pure routing function `decide`.

    retrieve -> grade -> decide() --correct--> generate -> END
                              \--else--> rewrite_query -> web_search -> grade_web -> generate

Verdict (CRAG paper, three-way): enough relevant local chunks -> `correct` (answer locally);
some -> `ambiguous` (keep local, add web); none -> `incorrect` (discard local, web only).
`generate` picks its context from the verdict and abstains when none survives, so with web
disabled `ambiguous` simply answers locally and `incorrect` abstains.

The graph is acyclic: the correction path runs at most once. No module singletons: everything
(settings, LLM client, retriever) is bound inside `build_graph`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, StateGraph

from .config import Settings, get_settings
from .llm import LLMClient
from .nodes.generate import generate
from .nodes.grade import grade_documents, verdict_for
from .nodes.grade_web import grade_web
from .nodes.retrieve import retrieve
from .nodes.rewrite_query import rewrite_query
from .nodes.web_search import web_search
from .observability import span
from .retrieval import Retriever
from .state import CRAGState


def decide(state: CRAGState, settings: Settings | None = None) -> str:
    """Conditional edge after grading. PURE: reads grades + settings, returns the next node name."""
    s = settings or get_settings()
    verdict = verdict_for(state.get("grades", []), s.correct_threshold, s.ambiguous_threshold)
    if verdict == "correct" or not s.web_enabled:
        return "generate"
    return "rewrite_query"


def _traced(name: str, fn: Callable[[CRAGState], dict]) -> Callable[[CRAGState], dict]:
    def run(state: CRAGState) -> dict:
        with span(name):
            return fn(state)

    return run


def build_graph(
    settings: Settings | None = None,
    *,
    client: LLMClient | None = None,
    retriever: Retriever | None = None,
    check_index: bool | None = None,
) -> Any:
    """Compile the graph. `retriever` is injectable for tests; the default one also checks that
    an index exists and degrades to the web path when it does not."""
    s = settings or get_settings()
    llm = client or LLMClient(s)
    if check_index is None:
        check_index = retriever is None
    ret = retriever or Retriever(s)

    g = StateGraph(CRAGState)
    nodes: dict[str, Callable[[CRAGState], dict]] = {
        "retrieve": lambda st: retrieve(st, ret, s, check_index=check_index),
        "grade": lambda st: grade_documents(st, llm, s),
        "rewrite_query": lambda st: rewrite_query(st, llm),
        "web_search": lambda st: web_search(st, s),
        "grade_web": lambda st: grade_web(st, llm, s),
        "generate": lambda st: generate(st, llm),
    }
    for name, fn in nodes.items():
        g.add_node(name, _traced(name, fn))

    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges(
        "grade",
        lambda st: decide(st, s),
        {"generate": "generate", "rewrite_query": "rewrite_query"},
    )
    g.add_edge("rewrite_query", "web_search")
    g.add_edge("web_search", "grade_web")
    g.add_edge("grade_web", "generate")
    g.add_edge("generate", END)
    return g.compile()
