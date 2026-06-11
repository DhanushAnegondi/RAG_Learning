"""Corpus ingestion: load -> chunk -> embed -> Chroma. (M1)

`chunk_documents` is a pure function (no embeddings/network) so it is unit-testable without a key.
"""
from __future__ import annotations

import glob
import os
from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import get_settings
from .llm import get_embeddings

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150


def load_documents(corpus_dir: str | None = None) -> List[Document]:
    """Load .md/.txt/.pdf files from the corpus directory into LangChain Documents."""
    corpus_dir = corpus_dir or get_settings().corpus_dir
    docs: List[Document] = []
    for path in sorted(glob.glob(os.path.join(corpus_dir, "**", "*"), recursive=True)):
        ext = os.path.splitext(path)[1].lower()
        if ext in (".md", ".txt"):
            with open(path, "r", encoding="utf-8") as fh:
                docs.append(Document(page_content=fh.read(), metadata={"source": path}))
        elif ext == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(path)
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
            docs.append(Document(page_content=text, metadata={"source": path}))
    return docs


def chunk_documents(
    docs: List[Document], chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP
) -> List[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    return splitter.split_documents(docs)


def build_index(corpus_dir: str | None = None, persist_dir: str | None = None):
    """Embed chunks with NVIDIAEmbeddings and persist a Chroma index. Needs a live NVIDIA_API_KEY."""
    from langchain_chroma import Chroma

    s = get_settings()
    chunks = chunk_documents(load_documents(corpus_dir or s.corpus_dir))
    if not chunks:
        raise ValueError(f"No documents found in {corpus_dir or s.corpus_dir}")
    return Chroma.from_documents(
        documents=chunks,
        embedding=get_embeddings(),
        persist_directory=persist_dir or s.persist_dir,
    )


def get_vectorstore():
    """Open the persisted Chroma index for retrieval."""
    from langchain_chroma import Chroma

    s = get_settings()
    return Chroma(persist_directory=s.persist_dir, embedding_function=get_embeddings())
