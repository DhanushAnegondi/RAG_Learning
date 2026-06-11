r"""The CRAG graph: nodes + the conditional edge `decide`.

    question -> retrieve -> grade -> decide() --[enough relevant]--> generate -> END
                                          \--[too few relevant]--> transform_query -> web_search -> generate -> END

`decide` is PURE: it reads the grades, returns the NAME of the next node, and never mutates state.
That separation is what makes the routing unit-testable (tests/test_decide.py) and is the one
function the interview hinges on.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from .config import get_settings
from .nodes.generate import generate
from .nodes.grade import grade_documents
from .nodes.retrieve import retrieve
from .nodes.transform_query import transform_query
from .nodes.web_search import web_search
from .state import CRAGState


def decide(state: dict) -> str:
    """Conditional edge. Enough relevant chunks -> answer; otherwise -> correction path."""
    grades = state.get("grades", [])
    n_relevant = sum(1 for g in grades if g)
    threshold = get_settings().relevance_threshold
    return "generate" if n_relevant >= threshold else "transform_query"


def build_graph():
    g = StateGraph(CRAGState)
    g.add_node("retrieve", retrieve)
    g.add_node("grade", grade_documents)
    g.add_node("generate", generate)
    g.add_node("transform_query", transform_query)
    g.add_node("web_search", web_search)

    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges(
        "grade",
        decide,
        {"generate": "generate", "transform_query": "transform_query"},
    )
    g.add_edge("transform_query", "web_search")
    g.add_edge("web_search", "generate")
    g.add_edge("generate", END)
    return g.compile()
