"""Corrective RAG (CRAG) — self-correcting retrieval as a LangGraph state machine."""

__all__ = ["build_graph", "decide", "CRAGState"]

from .state import CRAGState
from .graph import build_graph, decide
