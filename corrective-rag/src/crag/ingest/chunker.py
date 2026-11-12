"""Header-aware chunking.

Why split by markdown headers first: policy docs are organised by section, and a chunk that
carries its section title ("Fees > NSF") retrieves and cites far better than an arbitrary
800-character window. Oversized sections are then split recursively with overlap.

`chunk_id` is a sha256 of source + section + ordinal + content, so it is stable for unchanged
content and changes when the chunk changes; the incremental indexer relies on that.
"""

from __future__ import annotations

import hashlib

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3"), ("####", "h4")]


def make_chunk_id(source: str, section: str, ordinal: int, content: str) -> str:
    h = hashlib.sha256()
    for part in (source, section, str(ordinal), content):
        h.update(part.encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def _sections(doc: Document) -> list[tuple[str, str]]:
    """(section_path, text) pairs. Non-markdown sources are one section with an empty path."""
    source = str(doc.metadata.get("source", ""))
    if not source.lower().endswith(".md"):
        return [("", doc.page_content)]
    splitter = MarkdownHeaderTextSplitter(_HEADERS, strip_headers=False)
    out: list[tuple[str, str]] = []
    for piece in splitter.split_text(doc.page_content):
        path = " > ".join(piece.metadata[k] for _, k in _HEADERS if k in piece.metadata)
        out.append((path, piece.page_content))
    return out or [("", doc.page_content)]


def chunk_documents(
    docs: list[Document], chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP
) -> list[Document]:
    """Split documents into chunks with metadata: source, section, ordinal, chunk_id."""
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks: list[Document] = []
    for doc in docs:
        source = str(doc.metadata.get("source", ""))
        ordinal = 0
        for section, text in _sections(doc):
            for piece in splitter.split_text(text):
                if not piece.strip():
                    continue
                meta = {
                    **doc.metadata,
                    "source": source,
                    "section": section,
                    "ordinal": ordinal,
                    "chunk_id": make_chunk_id(source, section, ordinal, piece),
                }
                chunks.append(Document(page_content=piece, metadata=meta))
                ordinal += 1
    return chunks
