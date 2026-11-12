"""Load md/txt/pdf files from the corpus directory into Documents.

`source` is the path relative to the corpus dir with forward slashes: stable across machines and
OSes, so chunk ids and citations do not change when the repo is cloned elsewhere.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from langchain_core.documents import Document

SUPPORTED = {".md", ".txt", ".pdf"}


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_documents(corpus_dir: str | Path | None = None) -> list[Document]:
    """Load every supported file under `corpus_dir` (recursive, sorted for determinism)."""
    if corpus_dir is None:
        from ..config import get_settings

        corpus_dir = get_settings().corpus_dir
    root = Path(corpus_dir)
    docs: list[Document] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        ext = path.suffix.lower()
        if ext not in SUPPORTED:
            continue
        if ext == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        else:
            text = path.read_text(encoding="utf-8-sig")
        source = path.relative_to(root).as_posix()
        docs.append(Document(page_content=text, metadata={"source": source}))
    return docs
