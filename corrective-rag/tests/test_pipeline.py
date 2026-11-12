"""pipeline.answer: output contract, never raises on runtime faults, ValueError on bad input."""

import json
from pathlib import Path

import pytest

from crag import Answer, answer, llm
from crag.config import Settings
from crag.ingest import build_index
from crag.nodes import web_search as ws

from .fakes import HashEmbeddings
from .fakes_pipeline import PipelineChat

FEES = (
    "# Fees\n\n## NSF fee\nCode FEE-NSF-02 charges 35 dollars per returned payment.\n\n"
    "## Late fee\nCode FEE-LATE-01 charges 15 dollars after a 10 day grace period.\n"
)
RATES = "# Rates\n\n## Personal\nPersonal loan APR ranges from 8 to 24 percent.\n"
Q = "What does FEE-NSF-02 charge per returned payment?"


@pytest.fixture
def env(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "fees.md").write_text(FEES, encoding="utf-8")
    (corpus / "rates.md").write_text(RATES, encoding="utf-8")
    s = Settings(
        _env_file=None,
        corpus_dir=str(corpus),
        persist_dir=str(tmp_path / "store"),
        trace_dir=str(tmp_path / "traces"),
        max_retries=0,
        backoff_base_s=0.0,
        fallback_models=[],
        retrieval_mode="hybrid",
    )
    emb = HashEmbeddings()
    llm.set_embeddings_factory(lambda: emb)
    build_index(s, embeddings=emb)
    return s, emb, tmp_path


def web(monkeypatch, error=None):
    def fake(q, n, t):
        if error:
            raise error
        return [{"body": "web fact", "href": "http://w.io", "title": "W"}]

    monkeypatch.setattr(ws, "_ddgs_text", fake)


def test_happy_path_contract(env, monkeypatch):
    s, _, tmp = env
    web(monkeypatch)
    llm.set_chat_factory(
        lambda _m: PipelineChat(is_relevant=lambda t: "FEE-NSF-02" in t, answer="35 dollars [1].")
    )
    a = answer(Q, settings=s)
    assert isinstance(a, Answer)
    assert a.route == "local" and not a.abstained and not a.degraded and a.errors == []
    assert a.answer == "35 dollars [1]."
    assert a.citations[0].source == "fees.md" and a.citations[0].section == "Fees > NSF fee"
    assert a.retrieved and a.retrieved[0].chunk_id and "FEE-NSF-02" in a.retrieved[0].text
    scores = [r.score for r in a.retrieved]
    assert scores == sorted(scores, reverse=True)
    assert a.llm_calls >= 2 and a.retries == 0 and a.latency_ms > 0
    # trace was written and carries the same id
    lines = [
        json.loads(x)
        for f in Path(s.trace_dir).glob("*.jsonl")
        for x in f.read_text(encoding="utf-8").splitlines()
    ]
    assert [t["trace_id"] for t in lines] == [a.trace_id]


@pytest.mark.parametrize("bad", ["", "   ", "x" * 1001])
def test_invalid_question_raises_value_error(env, bad):
    s, _, _ = env
    with pytest.raises(ValueError):
        answer(bad, settings=s)


def test_grader_raising_fails_open_and_still_answers(env, monkeypatch):
    s, _, _ = env
    web(monkeypatch)
    chat = PipelineChat(grade_error=Exception("[500] boom"), answer="ok [1]")
    llm.set_chat_factory(lambda _m: chat)
    a = answer(Q, settings=s)
    assert not a.abstained and a.route == "local"
    assert any("llm[grade]" in e for e in a.errors)


def test_generator_raising_gives_extractive_degraded_answer(env, monkeypatch):
    s, _, _ = env
    web(monkeypatch)
    llm.set_chat_factory(lambda _m: PipelineChat(generate_error=Exception("[401] nope")))
    a = answer(Q, settings=s)
    assert a.degraded and a.answer.startswith("I couldn't generate a full answer right now.")
    assert a.citations and a.errors


def test_embeddings_down_falls_back_to_bm25(env, monkeypatch):
    s, emb, _ = env
    web(monkeypatch)
    emb.fail = True
    llm.set_chat_factory(lambda _m: PipelineChat(is_relevant=lambda t: "FEE-NSF-02" in t))
    a = answer(Q, settings=s)
    assert a.degraded and a.retrieved and "FEE-NSF-02" in a.retrieved[0].text
    assert not a.abstained


def test_web_raising_on_incorrect_abstains_with_errors(env, monkeypatch):
    s, _, _ = env
    web(monkeypatch, error=ConnectionError("ddg down"))
    llm.set_chat_factory(lambda _m: PipelineChat(is_relevant=lambda t: False))
    a = answer(Q, settings=s)
    assert a.abstained and a.route == "abstain" and a.degraded
    assert any("web search failed" in e for e in a.errors)


def test_index_missing_degrades_and_uses_web(tmp_path, monkeypatch):
    s = Settings(
        _env_file=None,
        persist_dir=str(tmp_path / "nope"),
        trace_dir=str(tmp_path / "t"),
        max_retries=0,
        backoff_base_s=0.0,
        fallback_models=[],
    )
    web(monkeypatch)
    llm.set_chat_factory(
        lambda _m: PipelineChat(is_relevant=lambda t: "web" in t, answer="from web [1]")
    )
    a = answer(Q, settings=s)
    assert a.degraded and a.route == "web" and a.retrieved == []
    assert any("index missing" in e for e in a.errors)
    assert a.citations[0].url == "http://w.io"


def test_unexpected_node_exception_is_contained(env, monkeypatch):
    s, _, _ = env

    def boom(*a, **k):
        raise RuntimeError("bug in a node")

    monkeypatch.setattr("crag.graph.generate", boom)
    llm.set_chat_factory(lambda _m: PipelineChat())
    a = answer(Q, settings=s)
    assert a.abstained and a.route == "abstain" and a.degraded
    assert any("bug in a node" in e for e in a.errors)


def test_no_key_and_no_factory_never_raises(env, monkeypatch):
    s, _, _ = env
    web(monkeypatch)
    llm.reset_factories()
    llm.set_embeddings_factory(lambda: HashEmbeddings())
    a = answer(Q, settings=s)  # real chat factory -> PermanentError (no key) everywhere
    assert isinstance(a, Answer) and a.errors
