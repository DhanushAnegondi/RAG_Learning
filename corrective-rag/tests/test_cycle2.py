"""Regressions from the caching work: stale Chroma handle after a rebuild, uncited answers,
atomic BM25 snapshots."""

import pytest
from fastapi.testclient import TestClient

from crag import llm
from crag.api import create_app
from crag.ingest import build_index
from crag.pipeline import answer
from crag.retrieval import Retriever

from .fakes_pipeline import PipelineChat
from .test_pipeline import Q, env, web  # noqa: F401  (env is a fixture)


def _chat(**kw):
    kw.setdefault("is_relevant", lambda t: "FEE-NSF-02" in t)
    chat = PipelineChat(**kw)
    llm.set_chat_factory(lambda _m: chat)
    return chat


def _assert_clean_local(a):
    assert a.route == "local" and not a.degraded, a.errors
    assert not any("dense retrieval failed" in e for e in a.errors)
    assert a.retrieved


def test_answer_after_rebuild_is_not_degraded(env, monkeypatch):  # noqa: F811
    s, emb, _ = env
    web(monkeypatch)
    _chat()
    _assert_clean_local(answer(Q, settings=s))
    build_index(s, rebuild=True, embeddings=emb)  # new collection UUID under the cached engine
    _assert_clean_local(answer(Q, settings=s))


def test_dense_retries_once_on_stale_collection(env, monkeypatch):  # noqa: F811
    """Even if the manifest mtime did not change, a NotFound from Chroma reopens and retries."""
    s, _, _ = env
    web(monkeypatch)
    _chat()
    r = Retriever(s)
    assert r.retrieve(Q)
    real = r._vectorstore()
    calls = []

    class Stale:
        def similarity_search_with_score(self, *a, **k):
            calls.append(1)
            raise RuntimeError("Collection abc does not exist.")

    r._store = Stale()
    r._store_manifest_mtime = r._manifest_mtime()
    out = r.retrieve(Q)
    assert calls == [1] and out
    assert r._store is not real and not isinstance(r._store, Stale)  # reopened
    assert any("dense" in c.ranks for c in out)


def test_api_survives_rebuild(env, monkeypatch):  # noqa: F811
    s, emb, _ = env
    web(monkeypatch)
    _chat()
    client = TestClient(create_app(s))
    first = client.post("/v1/ask", json={"question": Q}).json()
    assert first["route"] == "local" and not first["degraded"]
    build_index(s, rebuild=True, embeddings=emb)
    second = client.post("/v1/ask", json={"question": Q}).json()
    assert second["route"] == "local" and not second["degraded"], second["errors"]
    assert not any("dense retrieval failed" in e for e in second["errors"])


@pytest.mark.parametrize(
    "text",
    ["I don't know.", "I do not know the answer.", "The sources don't say.", "I’m not sure."],
)
def test_dont_know_without_citation_is_abstained(env, monkeypatch, text):  # noqa: F811
    s, _, _ = env
    web(monkeypatch)
    _chat(answer=text)
    a = answer(Q, settings=s)
    assert a.abstained and a.route == "abstain" and a.citations == []


def test_uncited_answer_is_flagged_degraded(env, monkeypatch):  # noqa: F811
    s, _, _ = env
    web(monkeypatch)
    _chat(answer="NSF is 35 dollars [99].")
    a = answer(Q, settings=s)
    assert not a.abstained and a.citations == []
    assert a.degraded and any("no valid citations" in e for e in a.errors)
    assert "[99]" not in a.answer


def test_cited_answer_stays_clean(env, monkeypatch):  # noqa: F811
    s, _, _ = env
    web(monkeypatch)
    _chat(answer="NSF is 35 dollars [1].")
    a = answer(Q, settings=s)
    assert a.citations and not a.degraded


def test_bm25_search_uses_one_snapshot_even_if_replaced_mid_search(env):  # noqa: F811
    s, _, _ = env
    r = Retriever(s.model_copy(update={"retrieval_mode": "bm25"}))
    records, model = r._load_bm25()
    assert len(records) > 1
    tiny = ([records[0]], model, r._bm25_snapshot[2])

    class Swapping:
        def get_scores(self, tokens):
            r._bm25_snapshot = tiny  # concurrent reload lands between scoring and record lookup
            return model.get_scores(tokens)

    r._bm25_snapshot = (records, Swapping(), r._bm25_snapshot[2])
    out = r.retrieve("FEE-NSF-02 returned payment")  # must not IndexError or mix corpora
    ids = {rec["id"] for rec in records}
    assert out and all(c.chunk_id in ids for c in out)
    assert any("FEE-NSF-02" in c.text for c in out)
