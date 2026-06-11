"""Curated ingest with source tagging.

Reuses crag's load/chunk, but prepends each chunk with its source experience (employer), so every
retrieved chunk carries who it belongs to. This stops the model from attributing one employer's work
to another (the cross-experience slip seen in early runs).
"""
from __future__ import annotations

import os

from crag.ingest import chunk_documents, load_documents
from crag.llm import get_embeddings

from .config import configure_crag, get_settings


def _experience_label(source_path: str, corpus_dir: str) -> str:
    """Top-level experience folder for a doc. Maps both `Rocket/...` and `interview/Rocket/...`
    to `Rocket`."""
    rel = os.path.relpath(source_path, corpus_dir).replace("\\", "/")
    parts = rel.split("/")
    if parts[0] == "interview" and len(parts) > 1:
        return parts[1]
    return parts[0]


def build_index():
    from langchain_chroma import Chroma

    s = configure_crag(get_settings())
    chunks = chunk_documents(load_documents(s.corpus_dir))
    if not chunks:
        raise ValueError(f"No documents found in {s.corpus_dir}")
    for c in chunks:
        label = _experience_label(c.metadata.get("source", ""), s.corpus_dir)
        c.metadata["experience"] = label
        c.page_content = f"[Experience: {label}]\n{c.page_content}"
    Chroma.from_documents(
        documents=chunks, embedding=get_embeddings(), persist_directory=s.persist_dir
    )
    return s
