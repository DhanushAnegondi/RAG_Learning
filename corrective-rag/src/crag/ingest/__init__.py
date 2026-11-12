"""Ingestion package: load -> chunk -> incrementally index (Chroma + BM25).

The v0 names `load_documents`, `chunk_documents`, `get_vectorstore` stay importable from here."""

from .chunker import CHUNK_OVERLAP, CHUNK_SIZE, chunk_documents, make_chunk_id
from .indexer import (
    BM25_FILE,
    MANIFEST,
    IndexReport,
    build_index,
    get_vectorstore,
    index_present,
    index_ready,
    index_retrievable,
)
from .loader import content_hash, load_documents

__all__ = [
    "BM25_FILE",
    "CHUNK_OVERLAP",
    "CHUNK_SIZE",
    "MANIFEST",
    "IndexReport",
    "build_index",
    "chunk_documents",
    "content_hash",
    "get_vectorstore",
    "index_present",
    "index_ready",
    "index_retrievable",
    "load_documents",
    "make_chunk_id",
]
