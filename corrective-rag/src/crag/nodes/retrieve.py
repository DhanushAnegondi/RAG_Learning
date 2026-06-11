"""retrieve node — top-k chunks from the vector store for the question."""
from __future__ import annotations

from ..config import get_settings
from ..ingest import get_vectorstore


def retrieve(state: dict) -> dict:
    store = get_vectorstore()
    k = get_settings().top_k
    docs = store.similarity_search(state["question"], k=k)
    return {"documents": docs, "steps": state.get("steps", []) + ["retrieve"]}
