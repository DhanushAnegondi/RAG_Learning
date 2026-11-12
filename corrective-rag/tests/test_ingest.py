"""Chunking is pure; the indexer is idempotent and incremental (fake embeddings, tmp dir)."""

import json
from pathlib import Path

import pytest
from langchain_core.documents import Document

from crag.config import Settings
from crag.ingest import build_index, chunk_documents, load_documents
from crag.ingest.indexer import BM25_FILE, MANIFEST, get_vectorstore

from .fakes import HashEmbeddings

FEES = """# Fees

## NSF fee
Code FEE-NSF-02 charges 35 dollars per returned payment.

## Late fee
Code FEE-LATE-01 charges 15 dollars after a 10 day grace period.
"""
RATES = """# Rates

## Personal loans
Personal loans carry an APR between 8 and 24 percent depending on credit tier.
"""
AUTO = "Auto loans need proof of insurance before funding. Term up to 72 months."


def test_chunk_splits_long_doc():
    long = Document(page_content="word " * 1000, metadata={"source": "x"})
    chunks = chunk_documents([long], chunk_size=200, chunk_overlap=20)
    assert len(chunks) > 1 and all(isinstance(c, Document) for c in chunks)


def test_chunk_metadata_and_stable_ids():
    doc = Document(page_content=FEES, metadata={"source": "policy/fees.md"})
    a, b = chunk_documents([doc]), chunk_documents([doc])
    assert [c.metadata["chunk_id"] for c in a] == [c.metadata["chunk_id"] for c in b]
    assert len({c.metadata["chunk_id"] for c in a}) == len(a)
    nsf = next(c for c in a if "FEE-NSF-02" in c.page_content)
    assert nsf.metadata["source"] == "policy/fees.md"
    assert nsf.metadata["section"] == "Fees > NSF fee"


def test_load_documents_reads_supported_types_with_relative_posix_source(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.md").write_text("# hello", encoding="utf-8")
    (tmp_path / "b.txt").write_text("world", encoding="utf-8")
    (tmp_path / "ignore.bin").write_text("nope", encoding="utf-8")
    docs = load_documents(str(tmp_path))
    assert {d.metadata["source"] for d in docs} == {"sub/a.md", "b.txt"}


@pytest.fixture
def env(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "fees.md").write_text(FEES, encoding="utf-8")
    (corpus / "rates.md").write_text(RATES, encoding="utf-8")
    (corpus / "auto.txt").write_text(AUTO, encoding="utf-8")
    settings = Settings(_env_file=None, corpus_dir=str(corpus), persist_dir=str(tmp_path / "store"))
    return settings, corpus, HashEmbeddings()


def _store_ids(settings, emb) -> set[str]:
    return set(get_vectorstore(settings, emb).get()["ids"])


def test_first_build_indexes_everything(env):
    s, _, emb = env
    r = build_index(s, embeddings=emb)
    assert sorted(r.added_files) == ["auto.txt", "fees.md", "rates.md"]
    assert r.chunks_embedded == emb.embedded > 0 and r.chunks_deleted == 0
    persist = Path(s.persist_dir)
    assert (persist / MANIFEST).exists() and (persist / BM25_FILE).exists()
    bm25 = json.loads((persist / BM25_FILE).read_text(encoding="utf-8"))
    assert len(bm25) == r.chunks_embedded == len(_store_ids(s, emb))


def test_rerun_without_changes_embeds_nothing(env):
    s, _, emb = env
    build_index(s, embeddings=emb)
    before = emb.embedded
    r = build_index(s, embeddings=emb)
    assert emb.embedded == before
    assert r.chunks_embedded == 0 and r.chunks_deleted == 0
    assert sorted(r.unchanged_files) == ["auto.txt", "fees.md", "rates.md"]
    assert not (r.added_files or r.updated_files or r.removed_files)


def test_edit_one_file_reembeds_only_that_file(env):
    s, corpus, emb = env
    build_index(s, embeddings=emb)
    old_ids = _store_ids(s, emb)
    before = emb.embedded
    extra = "\n## Mortgages\nFixed 30 year rate.\n"
    (corpus / "rates.md").write_text(RATES + extra, encoding="utf-8")
    r = build_index(s, embeddings=emb)
    assert r.updated_files == ["rates.md"]
    assert sorted(r.unchanged_files) == ["auto.txt", "fees.md"]
    assert 0 < emb.embedded - before == r.chunks_embedded
    assert r.chunks_deleted > 0
    new_ids = _store_ids(s, emb)
    assert len(new_ids) == len(old_ids) + 1  # one new section; others keep their ids
    bm25 = json.loads((Path(s.persist_dir) / BM25_FILE).read_text(encoding="utf-8"))
    assert {x["id"] for x in bm25} == new_ids


def test_deleted_file_removes_its_chunks(env):
    s, corpus, emb = env
    build_index(s, embeddings=emb)
    fee_ids = {
        x["id"]
        for x in json.loads((Path(s.persist_dir) / BM25_FILE).read_text(encoding="utf-8"))
        if x["metadata"]["source"] == "fees.md"
    }
    assert fee_ids
    (corpus / "fees.md").unlink()
    before = emb.embedded
    r = build_index(s, embeddings=emb)
    assert r.removed_files == ["fees.md"] and r.chunks_deleted == len(fee_ids)
    assert emb.embedded == before
    assert not (fee_ids & _store_ids(s, emb))
    bm25 = json.loads((Path(s.persist_dir) / BM25_FILE).read_text(encoding="utf-8"))
    assert not ({x["id"] for x in bm25} & fee_ids)


def test_rebuild_reembeds_everything(env):
    s, _, emb = env
    first = build_index(s, embeddings=emb)
    r = build_index(s, rebuild=True, embeddings=emb)
    assert r.chunks_embedded == first.chunks_embedded
    assert len(_store_ids(s, emb)) == first.chunks_embedded


def test_empty_corpus_raises(tmp_path):
    (tmp_path / "c").mkdir()
    s = Settings(_env_file=None, corpus_dir=str(tmp_path / "c"), persist_dir=str(tmp_path / "p"))
    with pytest.raises(ValueError):
        build_index(s, embeddings=HashEmbeddings())


def _bm25_ids(s) -> list[str]:
    path = Path(s.persist_dir) / BM25_FILE
    return [x["id"] for x in json.loads(path.read_text(encoding="utf-8"))]


def test_crash_before_manifest_write_leaves_no_duplicates(env, monkeypatch):
    s, _, emb = env
    from crag.ingest import indexer

    real = indexer._write_json

    def flaky(path, data):
        if path.name == MANIFEST:
            raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(indexer, "_write_json", flaky)
    with pytest.raises(OSError):
        build_index(s, embeddings=emb)
    monkeypatch.setattr(indexer, "_write_json", real)
    build_index(s, embeddings=emb)
    ids = _bm25_ids(s)
    assert len(ids) == len(set(ids)) and set(ids) == _store_ids(s, emb)


def test_missing_bm25_triggers_rebuild(env):
    s, _, emb = env
    build_index(s, embeddings=emb)
    (Path(s.persist_dir) / BM25_FILE).unlink()
    r = build_index(s, embeddings=emb)
    assert r.chunks_embedded > 0
    assert set(_bm25_ids(s)) == _store_ids(s, emb)


def test_lost_chroma_collection_triggers_rebuild(env):
    # The sqlite file stays locked by the live client on Windows, so drop the collection instead.
    s, _, emb = env
    build_index(s, embeddings=emb)
    get_vectorstore(s, emb).delete_collection()
    r = build_index(s, embeddings=emb)
    assert r.chunks_embedded > 0
    ids = _store_ids(s, emb)
    assert ids and set(_bm25_ids(s)) == ids


def test_chunk_size_change_forces_rebuild(env, monkeypatch):
    s, _, emb = env
    build_index(s, embeddings=emb)
    from crag.ingest import indexer

    monkeypatch.setattr(indexer, "CHUNK_SIZE", 300)
    r = build_index(s, embeddings=emb)
    assert r.chunks_embedded > 0 and not r.unchanged_files


def test_utf8_bom_stripped(tmp_path):
    (tmp_path / "a.md").write_bytes(b"\xef\xbb\xbf# Title")
    assert load_documents(str(tmp_path))[0].page_content == "# Title"
