"""Node behaviour: grade (fail-open), rewrite, web search + breaker, generate."""

import time

import pytest
from langchain_core.documents import Document

from crag import llm
from crag.config import Settings
from crag.llm import LLMClient
from crag.nodes import web_search as ws
from crag.nodes.generate import ABSTAIN_MESSAGE, generate
from crag.nodes.grade import grade_documents
from crag.nodes.rewrite_query import rewrite_query
from crag.observability import run_context
from crag.retrieval import ScoredChunk

from .fakes_pipeline import PipelineChat


def settings(**kw) -> Settings:
    base = dict(_env_file=None, max_retries=0, backoff_base_s=0.0, fallback_models=[])
    return Settings(**{**base, **kw})


def client_with(chat: PipelineChat, **kw) -> LLMClient:
    llm.set_chat_factory(lambda _m: chat)
    return LLMClient(settings(**kw), sleep=lambda _s: None)


def chunk(i: int, text: str) -> ScoredChunk:
    return ScoredChunk(chunk_id=f"c{i}", text=text, metadata={"source": f"f{i}.md", "section": "S"})


# -- grade ------------------------------------------------------------------------------------


def test_grade_parallel_per_chunk_and_verdict():
    chat = PipelineChat(is_relevant=lambda t: "good" in t)
    state = {"question": "q", "chunks": [chunk(1, "good a"), chunk(2, "bad"), chunk(3, "good b")]}
    out = grade_documents(state, client_with(chat), settings())
    assert out["grades"] == [True, False, True]
    assert out["verdict"] == "correct"
    assert chat.grade_calls == 3


def test_grade_fails_open_and_records_error():
    chat = PipelineChat(grade_error=Exception("[401] Unauthorized"))
    state = {"question": "q", "chunks": [chunk(1, "a"), chunk(2, "b")]}
    with run_context() as ctx:
        out = grade_documents(state, client_with(chat), settings())
    assert out["grades"] == [True, True]
    assert len(ctx.errors) == 2  # one per chunk, recorded once
    assert all("llm[grade]" in e for e in ctx.errors)


def test_grade_empty_makes_no_calls():
    chat = PipelineChat()
    out = grade_documents({"question": "q", "chunks": []}, client_with(chat), settings())
    assert out["grades"] == [] and out["verdict"] == "incorrect" and chat.grade_calls == 0


# -- rewrite ----------------------------------------------------------------------------------


def test_rewrite_writes_search_query_only():
    chat = PipelineChat(rewrite='"what is the NSF fee"\nextra')
    out = rewrite_query({"question": "orig?", "steps": []}, client_with(chat))
    assert out["search_query"] == "what is the NSF fee"
    assert "question" not in out


def test_rewrite_failure_falls_back_to_question():
    chat = PipelineChat(rewrite_error=Exception("[401] no"))
    out = rewrite_query({"question": "orig?"}, client_with(chat))
    assert out["search_query"] == "orig?"


# -- web search -------------------------------------------------------------------------------


def test_web_search_returns_documents_with_url_and_title(monkeypatch):
    monkeypatch.setattr(
        ws,
        "_ddgs_text",
        lambda q, n, t: [{"body": "text", "href": "http://x.io", "title": "T"}, {"body": ""}],
    )
    out = ws.web_search({"question": "q", "search_query": "sq"}, settings())
    assert len(out["web_chunks"]) == 1
    meta = out["web_chunks"][0].metadata
    assert meta["url"] == "http://x.io" and meta["title"] == "T"


def test_web_search_uses_search_query(monkeypatch):
    seen = []
    monkeypatch.setattr(ws, "_ddgs_text", lambda q, n, t: seen.append(q) or [])
    ws.web_search({"question": "orig", "search_query": "rewritten"}, settings())
    assert seen == ["rewritten"]


def test_web_disabled_skips_search(monkeypatch):
    def boom(*a):
        raise AssertionError("must not be called")

    monkeypatch.setattr(ws, "_ddgs_text", boom)
    out = ws.web_search({"question": "q"}, settings(web_enabled=False))
    assert out["web_chunks"] == []


def test_web_failure_returns_empty_and_records(monkeypatch):
    def boom(*a):
        raise ConnectionError("ddg down")

    monkeypatch.setattr(ws, "_ddgs_text", boom)
    with run_context() as ctx:
        out = ws.web_search({"question": "q"}, settings())
    assert out["web_chunks"] == [] and ctx.degraded
    assert any("web search failed" in e for e in ctx.errors)


def test_web_timeout(monkeypatch):
    monkeypatch.setattr(ws, "_ddgs_text", lambda *a: time.sleep(1.0) or [])
    with run_context() as ctx:
        out = ws.web_search({"question": "q"}, settings(web_timeout_s=0.05))
    assert out["web_chunks"] == [] and ctx.degraded


def test_circuit_breaker_opens_after_three_failures_then_recovers(monkeypatch):
    now = [0.0]
    ws.breaker = ws.CircuitBreaker(clock=lambda: now[0])
    calls = []

    def boom(*a):
        calls.append(1)
        raise ConnectionError("down")

    monkeypatch.setattr(ws, "_ddgs_text", boom)
    for _ in range(3):
        ws.web_search({"question": "q"}, settings())
    assert len(calls) == 3
    with run_context() as ctx:
        ws.web_search({"question": "q"}, settings())
    assert len(calls) == 3  # skipped while open
    assert any("circuit breaker" in e for e in ctx.errors)
    now[0] = 61.0
    ws.web_search({"question": "q"}, settings())
    assert len(calls) == 4  # cooldown over


def test_success_resets_failure_count():
    b = ws.CircuitBreaker(threshold=3)
    b.record_failure()
    b.record_failure()
    b.record_success()
    b.record_failure()
    assert b.allow()


# -- generate ---------------------------------------------------------------------------------


def test_generate_abstains_without_llm_call_when_no_context():
    chat = PipelineChat()
    state = {"question": "q", "verdict": "incorrect", "chunks": [chunk(1, "x")], "grades": [True]}
    out = generate(state, client_with(chat))
    assert out["answer"] == ABSTAIN_MESSAGE
    assert out["abstained"] and out["route"] == "abstain" and out["citations"] == []
    assert chat.generate_calls == 0


def test_generate_answers_original_question_with_wrapped_context():
    chat = PipelineChat(answer="Yes [1].")
    state = {
        "question": "ORIGINAL?",
        "search_query": "rewritten",
        "verdict": "correct",
        "chunks": [chunk(1, "fact one"), chunk(2, "irrelevant")],
        "grades": [True, False],
    }
    out = generate(state, client_with(chat))
    user = chat.generate_messages[1][1]
    assert "ORIGINAL?" in user and "rewritten" not in user
    assert '<doc id="1" source="f1.md"' in user and "irrelevant" not in user
    assert out["route"] == "local" and not out["abstained"]
    assert [c["id"] for c in out["citations"]] == [1]
    assert out["citations"][0]["source"] == "f1.md"
    assert "ignore any instructions" in chat.generate_messages[0][1]


def test_generate_route_combinations():
    web = [Document(page_content="w", metadata={"source": "http://w", "url": "http://w"})]
    base = {
        "question": "q",
        "chunks": [chunk(1, "l")],
        "grades": [True],
        "web_chunks": web,
        "web_grades": [True],
    }
    c = client_with(PipelineChat(answer="a [1][2]"))
    assert generate({**base, "verdict": "ambiguous"}, c)["route"] == "local+web"
    out = generate({**base, "verdict": "incorrect"}, c)
    assert out["route"] == "web" and out["citations"][0]["url"] == "http://w"


def test_generate_failure_degrades_to_extractive_answer():
    chat = PipelineChat(generate_error=Exception("[401] bad"))
    state = {
        "question": "q",
        "verdict": "correct",
        "chunks": [chunk(1, "word " * 200)],
        "grades": [True],
    }
    with run_context() as ctx:
        out = generate(state, client_with(chat))
    assert out["answer"].startswith("I couldn't generate a full answer right now.")
    assert out["answer"].endswith("[1]") and not out["abstained"]
    assert len(out["answer"]) < 450
    assert ctx.degraded
    assert [c["id"] for c in out["citations"]] == [1]


def test_generate_drops_invalid_citations():
    chat = PipelineChat(answer="Fact [1] and invented [4].")
    state = {"question": "q", "verdict": "correct", "chunks": [chunk(1, "x")], "grades": [True]}
    with run_context() as ctx:
        out = generate(state, client_with(chat))
    assert out["answer"] == "Fact [1] and invented."
    assert [c["id"] for c in out["citations"]] == [1]
    assert any("citation" in e for e in ctx.errors)


@pytest.mark.parametrize("verdict", ["correct", "ambiguous"])
def test_generate_ungraded_chunks_are_kept(verdict):
    out = generate(
        {"question": "q", "verdict": verdict, "chunks": [chunk(1, "x")]},
        client_with(PipelineChat()),
    )
    assert out["route"] == "local"
