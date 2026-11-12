"""Retriever: RRF math, BM25 exact-identifier win, hybrid fusion, degradation."""

import pytest

from crag.config import Settings
from crag.ingest import build_index
from crag.ingest.indexer import get_vectorstore
from crag.observability import run_context
from crag.retrieval import Retriever, ScoredChunk, rrf_fuse, tokenize

from .fakes import HashEmbeddings

DOCS = {
    "fees.md": (
        "# Fees\n\n## NSF fee one\nCode FEE-NSF-01 applies to deposit accounts, 25 dollars.\n\n"
        "## NSF fee two\nCode FEE-NSF-02 applies to loan payments, 35 dollars per return.\n"
    ),
    "rates.md": "# Rates\n\n## Personal\nPersonal loan APR ranges from 8 to 24 percent.\n",
    "hardship.md": "# Hardship\n\n## Relief\nBorrowers in hardship may request a payment plan.\n",
    "servicing.md": "# Servicing\n\n## Contact\nCall the servicing desk during business hours.\n",
}


def test_rrf_math():
    scores = rrf_fuse({"a": ["x", "y"], "b": ["y", "z"]}, k=60)
    assert scores["x"] == pytest.approx(1 / 61)
    assert scores["y"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["z"] == pytest.approx(1 / 62)
    assert max(scores, key=scores.get) == "y"  # agreement across retrievers wins


def test_tokenize_splits_identifiers():
    assert tokenize("FEE-NSF-02!") == ["fee", "nsf", "02"]


@pytest.fixture
def index(tmp_path):
    corpus = tmp_path / "c"
    corpus.mkdir()
    for name, text in DOCS.items():
        (corpus / name).write_text(text, encoding="utf-8")
    emb = HashEmbeddings()

    def settings(mode="hybrid", **kw):
        return Settings(
            _env_file=None,
            corpus_dir=str(corpus),
            persist_dir=str(tmp_path / "p"),
            retrieval_mode=mode,
            **kw,
        )

    build_index(settings(), embeddings=emb)
    return settings, emb


def _retriever(settings, emb):
    return Retriever(settings, vectorstore=get_vectorstore(settings, emb))


def test_bm25_exact_identifier_ranks_first(index):
    settings, emb = index
    out = _retriever(settings("bm25"), emb).retrieve("FEE-NSF-02")
    assert "FEE-NSF-02" in out[0].text
    assert out[0].ranks == {"bm25": 1}


def test_bm25_no_term_overlap_returns_nothing(index):
    settings, emb = index
    assert _retriever(settings("bm25"), emb).retrieve("zzzqqq") == []


def test_dense_mode_returns_scored_chunks(index):
    settings, emb = index
    out = _retriever(settings("dense"), emb).retrieve("personal loan APR percent")
    assert out and isinstance(out[0], ScoredChunk) and "APR" in out[0].text
    assert out[0].chunk_id == out[0].metadata["chunk_id"]


def test_hybrid_fuses_both_and_dedupes(index):
    settings, emb = index
    out = _retriever(settings("hybrid"), emb).retrieve("FEE-NSF-02 loan payments", k=3)
    ids = [c.chunk_id for c in out]
    assert len(ids) == len(set(ids)) <= 3
    assert "FEE-NSF-02" in out[0].text
    assert set(out[0].ranks) == {"dense", "bm25"}
    assert out == sorted(out, key=lambda c: c.score, reverse=True)


def test_hybrid_degrades_to_bm25_when_embeddings_fail(index):
    settings, emb = index
    r = _retriever(settings("hybrid"), emb)
    emb.fail = True
    with run_context() as ctx:
        out = r.retrieve("FEE-NSF-02")
    assert out and "FEE-NSF-02" in out[0].text
    assert set(out[0].ranks) == {"bm25"}
    assert ctx.degraded and ctx.errors


def test_dense_mode_falls_back_to_bm25_on_failure(index):
    settings, emb = index
    r = _retriever(settings("dense"), emb)
    emb.fail = True
    with run_context() as ctx:
        out = r.retrieve("FEE-NSF-02")
    assert out and ctx.degraded


def test_missing_bm25_degrades_to_dense_only(index):
    settings, emb = index
    s = settings("hybrid")
    (__import__("pathlib").Path(s.persist_dir) / "bm25.json").unlink()
    with run_context() as ctx:
        out = _retriever(s, emb).retrieve("personal loan APR")
    assert out and set(out[0].ranks) == {"dense"} and ctx.degraded


def test_everything_down_returns_empty_and_degraded(index):
    settings, emb = index
    s = settings("hybrid")
    (__import__("pathlib").Path(s.persist_dir) / "bm25.json").unlink()
    r = _retriever(s, emb)
    emb.fail = True
    with run_context() as ctx:
        assert r.retrieve("anything") == []
    assert ctx.degraded


def test_bm25_scores_positive_on_two_doc_corpus(tmp_path):
    corpus = tmp_path / "c"
    corpus.mkdir()
    (corpus / "a.txt").write_text("alpha policy covers refunds", encoding="utf-8")
    (corpus / "b.txt").write_text("beta policy covers chargebacks", encoding="utf-8")
    s = Settings(
        _env_file=None,
        corpus_dir=str(corpus),
        persist_dir=str(tmp_path / "p"),
        retrieval_mode="bm25",
    )
    emb = HashEmbeddings()
    build_index(s, embeddings=emb)
    out = Retriever(s, vectorstore=get_vectorstore(s, emb)).retrieve("refunds")
    assert out and "refunds" in out[0].text and out[0].score > 0
