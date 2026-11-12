"""Graph routing end to end with a fake retriever, fake chat and a patched web client."""

import pytest

from crag import llm
from crag.config import Settings
from crag.graph import build_graph
from crag.llm import LLMClient
from crag.nodes import web_search as ws
from crag.nodes.generate import ABSTAIN_MESSAGE
from crag.observability import run_context
from crag.retrieval import ScoredChunk

from .fakes_pipeline import PipelineChat

QUESTION = "What is the NSF fee?"


class FakeRetriever:
    def __init__(self, texts):
        self.chunks = [
            ScoredChunk(
                chunk_id=f"c{i}",
                text=t,
                metadata={"source": f"f{i}.md", "section": "S"},
                score=1.0 / (i + 1),
            )
            for i, t in enumerate(texts)
        ]
        self.queries = []

    def retrieve(self, query, k=None):
        self.queries.append(query)
        return self.chunks


def web_results(monkeypatch, results=None, error=None):
    seen = []

    def fake(query, n, t):
        seen.append(query)
        if error:
            raise error
        return (
            results
            if results is not None
            else [{"body": "web fact", "href": "http://w.io", "title": "W"}]
        )

    monkeypatch.setattr(ws, "_ddgs_text", fake)
    return seen


def run(texts, chat, **settings_kw):
    s = Settings(
        _env_file=None, max_retries=0, backoff_base_s=0.0, fallback_models=[], **settings_kw
    )
    llm.set_chat_factory(lambda _m: chat)
    retriever = FakeRetriever(texts)
    graph = build_graph(s, client=LLMClient(s, sleep=lambda _s: None), retriever=retriever)
    with run_context() as ctx:
        state = graph.invoke({"question": QUESTION, "steps": []})
    return state, retriever, ctx


def test_correct_route_is_local_and_skips_web(monkeypatch):
    seen = web_results(monkeypatch)
    chat = PipelineChat(is_relevant=lambda t: "good" in t)
    state, _, _ = run(["good one", "good two", "bad"], chat)
    assert state["verdict"] == "correct" and state["route"] == "local"
    assert state["steps"] == ["retrieve", "grade", "generate"]
    assert seen == [] and len(state["citations"]) >= 1


def test_ambiguous_route_keeps_local_and_adds_web(monkeypatch):
    seen = web_results(monkeypatch)
    chat = PipelineChat(is_relevant=lambda t: "good" in t or "web" in t, answer="a [1][2]")
    state, _, _ = run(["good one", "bad", "bad"], chat)
    assert state["verdict"] == "ambiguous" and state["route"] == "local+web"
    assert state["steps"] == [
        "retrieve",
        "grade",
        "rewrite_query",
        "web_search",
        "grade_web",
        "generate",
    ]
    assert seen == ["rewritten web query"]
    assert [c["id"] for c in state["citations"]] == [1, 2]
    assert state["citations"][1]["url"] == "http://w.io"


def test_ambiguous_with_irrelevant_web_stays_local(monkeypatch):
    web_results(monkeypatch)
    chat = PipelineChat(is_relevant=lambda t: "good" in t)
    state, _, _ = run(["good one", "bad"], chat)
    assert state["route"] == "local"


def test_incorrect_route_uses_web_only(monkeypatch):
    web_results(monkeypatch)
    chat = PipelineChat(is_relevant=lambda t: "web" in t, answer="from web [1]")
    state, _, _ = run(["bad one", "bad two"], chat)
    assert state["verdict"] == "incorrect" and state["route"] == "web"
    assert "bad one" not in chat.generate_messages[1][1]
    assert state["citations"][0]["url"] == "http://w.io"


def test_incorrect_and_web_irrelevant_abstains_without_generation_call(monkeypatch):
    web_results(monkeypatch)
    chat = PipelineChat(is_relevant=lambda t: False)
    state, _, _ = run(["bad"], chat)
    assert state["route"] == "abstain" and state["abstained"]
    assert state["answer"] == ABSTAIN_MESSAGE and chat.generate_calls == 0


def test_web_disabled_ambiguous_answers_locally(monkeypatch):
    seen = web_results(monkeypatch)
    chat = PipelineChat(is_relevant=lambda t: "good" in t)
    state, _, _ = run(["good", "bad"], chat, web_enabled=False)
    assert state["verdict"] == "ambiguous" and state["route"] == "local"
    assert "web_search" not in state["steps"] and seen == []


def test_web_disabled_incorrect_abstains(monkeypatch):
    web_results(monkeypatch)
    state, _, _ = run(["bad"], PipelineChat(is_relevant=lambda t: False), web_enabled=False)
    assert state["route"] == "abstain" and state["abstained"]


def test_web_failing_incorrect_abstains_and_reports(monkeypatch):
    web_results(monkeypatch, error=ConnectionError("down"))
    state, _, ctx = run(["bad"], PipelineChat(is_relevant=lambda t: False))
    assert state["route"] == "abstain"
    assert ctx.degraded and any("web search failed" in e for e in ctx.errors)


def test_web_failing_ambiguous_still_answers_locally(monkeypatch):
    web_results(monkeypatch, error=TimeoutError("slow"))
    state, _, _ = run(["good", "bad"], PipelineChat(is_relevant=lambda t: "good" in t))
    assert state["route"] == "local" and not state["abstained"]


def test_question_never_overwritten_while_search_query_is_rewritten(monkeypatch):
    seen = web_results(monkeypatch)
    chat = PipelineChat(is_relevant=lambda t: "web" in t, rewrite="totally different query")
    state, retriever, _ = run(["bad"], chat)
    assert state["question"] == QUESTION
    assert state["search_query"] == "totally different query"
    assert retriever.queries == [QUESTION]  # retrieval used the original
    assert seen == ["totally different query"]  # web used the rewrite
    assert f"Question: {QUESTION}" in chat.generate_messages[1][1]  # generation used the original


def test_graph_is_acyclic_correction_runs_once(monkeypatch):
    web_results(monkeypatch)
    state, _, _ = run(["bad"], PipelineChat(is_relevant=lambda t: "web" in t))
    assert state["steps"].count("web_search") == 1 and state["steps"].count("retrieve") == 1


@pytest.mark.parametrize("n_good,expected", [(0, "incorrect"), (1, "ambiguous"), (2, "correct")])
def test_thresholds_from_settings_drive_verdict(monkeypatch, n_good, expected):
    web_results(monkeypatch)
    texts = ["good"] * n_good + ["bad"] * (3 - n_good)
    state, _, _ = run(texts, PipelineChat(is_relevant=lambda t: "good" in t))
    assert state["verdict"] == expected
