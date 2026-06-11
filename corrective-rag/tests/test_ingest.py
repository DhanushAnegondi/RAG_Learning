"""Ingest: chunking is pure (no key); loading reads the right file types."""
from langchain_core.documents import Document

from crag.ingest import chunk_documents, load_documents


def test_chunk_splits_long_doc():
    long = Document(page_content="word " * 1000, metadata={"source": "x"})
    chunks = chunk_documents([long], chunk_size=200, chunk_overlap=20)
    assert len(chunks) > 1
    assert all(isinstance(c, Document) for c in chunks)


def test_load_documents_reads_md_and_txt_only(tmp_path):
    (tmp_path / "a.md").write_text("# hello", encoding="utf-8")
    (tmp_path / "b.txt").write_text("world", encoding="utf-8")
    (tmp_path / "ignore.bin").write_text("nope", encoding="utf-8")
    docs = load_documents(str(tmp_path))
    assert sorted(d.page_content for d in docs) == ["# hello", "world"]
