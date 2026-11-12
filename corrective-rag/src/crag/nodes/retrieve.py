"""retrieve node: top-k chunks for the ORIGINAL question (hybrid by default)."""

from __future__ import annotations

from ..config import Settings
from ..ingest import index_retrievable
from ..observability import current_context
from ..retrieval import Retriever
from ..state import CRAGState


def retrieve(
    state: CRAGState, retriever: Retriever, settings: Settings, *, check_index: bool = True
) -> dict:
    steps = [*state.get("steps", []), "retrieve"]
    if check_index and not index_retrievable(settings):
        # No index is degraded-but-answerable: grading sees zero chunks, the verdict is
        # `incorrect`, and the web path runs.
        ctx = current_context()
        if ctx is not None:
            ctx.mark_degraded("index missing: run `crag ingest`; local retrieval skipped")
        return {"chunks": [], "steps": steps}
    return {"chunks": retriever.retrieve(state["question"], settings.top_k), "steps": steps}
