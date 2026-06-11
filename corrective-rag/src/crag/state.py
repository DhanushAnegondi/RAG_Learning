"""The graph state — one dict threaded through every node.

`total=False` so nodes can return PARTIAL updates (LangGraph merges them into the state).
This single shared contract is the whole point of M3: nodes communicate through state, not args.
"""
from __future__ import annotations

from typing import List, TypedDict

from langchain_core.documents import Document


class CRAGState(TypedDict, total=False):
    question: str                 # the (possibly rewritten) query
    documents: List[Document]     # chunks retrieved from the vector store
    grades: List[bool]            # parallel to `documents`; True = relevant (set by grade node)
    web_results: List[Document]   # filled only when the correction path runs
    generation: str               # the final answer
    steps: List[str]              # ordered trace of nodes visited (for the CLI to show the route)
