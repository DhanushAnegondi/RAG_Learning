"""Offline tests for the harness itself (no key, no network, no crag import)."""

from __future__ import annotations

import json

import pytest
from eval import metrics, report
from eval.chaos import FaultInjector, exception_for
from eval.dataset import load_eval_set
from eval.judge import Judge, key_fact_match, parse_json


def test_evidence_rank_and_hit_mrr():
    texts = ["Intro text", "The  minimum FICO\nis **660**", "other"]
    assert metrics.evidence_rank(["minimum fico is **660**"], texts) == 2  # case + whitespace
    assert metrics.evidence_rank(["nope"], texts) is None
    assert metrics.evidence_rank([], texts) is None
    ranks = [1, 2, None, 4]
    assert metrics.hit_at_k(ranks, 1) == pytest.approx(0.25)
    assert metrics.hit_at_k(ranks, 4) == pytest.approx(0.75)
    assert metrics.mrr(ranks) == pytest.approx((1 + 0.5 + 0 + 0.25) / 4)


def test_multi_evidence_union():
    assert metrics.evidence_rank(["aaa", "bbb"], ["aaa x", "y bbb"]) == 2


def test_percentile():
    assert metrics.percentile([10, 20, 30, 40], 50) == 25
    assert metrics.percentile([], 95) is None


def test_key_fact_match():
    assert key_fact_match("660.", "The minimum score is 660.") == 1.0
    assert key_fact_match("$15 per returned payment", "A fee of $15 applies") == 1.0
    assert key_fact_match("$5,000 and 43%", "up to 5000 at 12%") == 0.5
    assert key_fact_match("660", "score 6600") == 0.0  # no partial-number match
    assert key_fact_match("Code FEE-NSF-02", "fee-nsf-02 applies") == 1.0
    assert key_fact_match("I don't know", "whatever") is None


def row(**kw):
    base = {
        "category": "semantic",
        "expected_route": "local",
        "evidence": ["x"],
        "rank": 1,
        "route": "local",
        "abstained": False,
        "crashed": False,
        "answer": "a",
        "faults": [],
        "latency_ms": 10.0,
        "llm_calls": 3,
    }
    return {**base, **kw}


def test_recovery_rate_formula():
    rows = [
        row(faults=[["chat", "429"]]),  # recovered
        row(faults=[["chat", "500"]], crashed=True, answer=""),  # crashed
        row(faults=[["web", "web_down"]], answer="", abstained=True),  # explicit abstain: usable
        row(faults=[["chat", "timeout"]], answer="  "),  # empty answer: not usable
        row(),  # no fault: not in denominator
    ]
    r = metrics.recovery_rate(rows)
    assert (r["faulted_questions"], r["recovered"]) == (4, 2)
    assert r["rate"] == 0.5
    assert metrics.recovery_rate([row()])["rate"] is None


def test_aggregate_routing_abstention_crash():
    rows = [
        row(),
        row(route="local+web"),
        row(category="unanswerable", expected_route="abstain", abstained=True, evidence=[]),
        row(category="unanswerable", expected_route="abstain", route="web", evidence=[]),
        row(crashed=True, answer=""),
    ]
    a = metrics.aggregate(rows)
    assert a["routing_exact"] == pytest.approx(2 / 5)  # row0 and the abstain row
    assert a["routing_lenient"] == pytest.approx(3 / 5)  # + local+web accepted for local
    assert a["abstention_accuracy"] == 0.5
    assert a["crash_rate"] == pytest.approx(1 / 5)
    assert a["false_abstention_rate"] == 0.0
    assert set(metrics.by_category(rows)) == {"semantic", "unanswerable"}


def test_fault_injector_is_seeded_and_gated():
    inj = FaultInjector(1.0, seed=3)
    assert inj.draw("chat") is None  # inactive outside begin/end
    inj.begin("q1")
    kinds = [inj.draw("structured") for _ in range(20)]
    assert all(k is not None for k in kinds)
    assert len(inj.end()) == 20
    a, b = FaultInjector(0.5, 3), FaultInjector(0.5, 3)
    a.begin("q"), b.begin("q")
    assert [a.draw("chat") for _ in range(30)] == [b.draw("chat") for _ in range(30)]
    assert isinstance(exception_for("timeout"), TimeoutError)
    assert "[429]" in str(exception_for("429"))


def test_judge_parses_and_retries(monkeypatch):
    class Chat:
        def __init__(self):
            self.n = 0

        def invoke(self, _p):
            self.n += 1
            if self.n == 1:
                raise Exception("[429] Too Many Requests")
            return type("R", (), {"content": '```json\n{"score": 1, "reason": "ok"}\n```'})()

    j = Judge(chat=Chat(), max_attempts=3)
    import tenacity

    monkeypatch.setattr(tenacity.nap.time, "sleep", lambda _s: None)  # restored after the test
    assert j.correctness("q", "t", "a") == {"score": 1, "reason": "ok"}
    assert parse_json('x {"a": 1} y') == {"a": 1}


def test_eval_set_valid():
    rows = load_eval_set()
    assert len(rows) >= 30 and len({r["id"] for r in rows}) == len(rows)


def _result_file(tmp_path, system, rate, ts, **agg):
    d = {
        "meta": {
            "system": system,
            "suite": "chaos",
            "mode": "offline",
            "timestamp_utc": ts,
            "n_rows": 40,
            "corpus_hash": "c" * 64,
            "eval_set_hash": "e" * 64,
            "seed": 7,
            "rate": rate,
            "commit": "abc1234567",
            "dirty": True,
            "src_tree_hash": "f" * 64,
            "network_blocked": True,
        },
        "aggregates": {"k": 4, **agg},
        "by_category": {},
        "rows": [],
    }
    p = tmp_path / f"{system}_{rate}_{ts[:4]}.json"
    p.write_text(json.dumps(d), encoding="utf-8")


def test_report_chaos_by_rate_and_not_run(tmp_path):
    _result_file(
        tmp_path,
        "v0",
        0.3,
        "2026-01-01T00:00:00+00:00",
        error_recovery_rate=0.25,
        crash_rate=0.75,
        hit_at_4=0.99,
    )
    _result_file(tmp_path, "v0", 0.3, "2025-01-01T00:00:00+00:00", error_recovery_rate=0.9)
    _result_file(tmp_path, "v1", 0.0, "2026-01-01T00:00:00+00:00", error_recovery_rate=1.0)
    best = report.latest_runs(tmp_path)
    assert len(best) == 2  # newest per (system, suite, mode, rate) wins
    md = report.render(best)
    assert "| 0.3 | v0 | n/a | 25.0% | n/a | 75.0%" in md
    assert "| 0.3 | v1 | not run" in md and "| 0 | v0 | not run" in md
    assert "90.0%" not in md  # the older run is not used
    chaos = md.split("## Chaos, offline")[1].split("## Chaos, live")[0]
    assert "hit@" not in chaos and "MRR" not in chaos and "99.0%" not in chaos
    assert "not run for either system" in md  # quality and live chaos
    assert "dirty=True" in md and "network blocked" in md


def test_hermetic_blocks_non_loopback():
    import socket

    from eval.hermetic import block_network

    seen: list[str] = []
    with block_network(seen):
        with pytest.raises(ConnectionError):
            socket.getaddrinfo("example.com", 443)
        s = socket.socket()
        with pytest.raises(ConnectionError):
            s.connect(("93.184.216.34", 80))
        s.close()
        socket.getaddrinfo("localhost", 80)  # loopback still allowed
    assert seen == ["example.com", "93.184.216.34"]
    socket.getaddrinfo("localhost", 80)  # restored


def test_ddgs_proxy_is_patched_offline():
    """`ddgs.DDGS` is a lazy proxy; the fake must still intercept `DDGS(...).text(...)`."""
    import ddgs
    from eval import chaos

    inj = FaultInjector(0.0)
    with chaos._patched(chaos._web_patches(inj, offline=True)):
        out = list(ddgs.DDGS(timeout=1).text("fee code", max_results=4))
    assert out and out[0]["href"].startswith("https://example.invalid")


def test_code_provenance(tmp_path):
    from eval.systems import code_provenance

    (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
    h1 = code_provenance(tmp_path, tmp_path)["src_tree_hash"]
    (tmp_path / "a.py").write_text("x = 2", encoding="utf-8")
    assert code_provenance(tmp_path, tmp_path)["src_tree_hash"] != h1


def test_chaos_robustness_rates():
    rows = [
        row(),
        row(abstained=True, answer="I don't know"),
        row(crashed=True, answer=""),
        row(degraded=True, retries=3),
    ]
    a = metrics.aggregate(rows)
    assert a["answered_rate"] == 0.5 and a["abstain_rate"] == 0.25
    assert a["degraded_rate"] == 0.25 and a["mean_retries"] == 0.75


def test_v1_context_uses_answer_context_never_retrieved():
    from types import SimpleNamespace as NS

    from eval.systems import context_texts_from

    with_ctx = NS(retrieved=[NS(text="r1"), NS(text="r2")], context=[NS(text="c1", origin="web")])
    assert context_texts_from(with_ctx) == ["c1"]
    without = NS(retrieved=[NS(text="r1")])  # no `context` attribute: unavailable, no fallback
    assert context_texts_from(without) is None
    assert context_texts_from(NS(context=[{"text": "d"}])) == ["d"]


def test_fault_draws_ignore_thread_order_and_count_calls():
    import threading

    from eval.chaos import call_key

    def run(order):
        inj = FaultInjector(0.5, seed=11)
        inj.begin("q9")
        out = {}

        def work(text):
            out[text] = inj.draw("structured", call_key((text,)))

        threads = [threading.Thread(target=work, args=(t,)) for t in order]
        for t in threads:
            t.start()
            t.join()
        return out, inj

    texts = [f"chunk {i}" for i in range(12)]
    a, inj = run(texts)
    b, _ = run(list(reversed(texts)))
    assert a == b  # same input -> same draw, whatever the order
    assert inj.calls["structured"] == 12 and inj.calls["chat"] == 0
    inj.begin("q9")  # same input repeated (a retry) gets the next occurrence index
    first = inj.draw("chat", "k")
    seq = [first] + [inj.draw("chat", "k") for _ in range(30)]
    assert any(x is None for x in seq) and any(x is not None for x in seq)
    assert inj.calls["chat"] == 31


def test_report_comparability_gate(tmp_path):
    def mk(system, **over):
        d = {
            "meta": {
                "system": system,
                "suite": "chaos",
                "mode": "offline",
                "timestamp_utc": "2026-01-01T00:00:00+00:00",
                "n_rows": 40,
                "seed": 7,
                "rate": 0.3,
                "corpus_hash": "c" * 64,
                "eval_set_hash": "e" * 64,
                "commit": "a",
                "dirty": False,
                "src_tree_hash": "s" * 64,
                **over,
            },
            "aggregates": {"k": 4, "crash_rate": 0.5},
            "by_category": {},
            "rows": [],
        }
        (tmp_path / f"{system}.json").write_text(json.dumps(d), encoding="utf-8")

    mk("v0")
    mk("v1", seed=8, corpus_hash="d" * 64)
    md = report.render(report.latest_runs(tmp_path))
    assert "not comparable: corpus_hash, seed" in md
    # quality additionally gates on top_k and judge_model
    q0 = (tmp_path / "x", {"meta": {"top_k": 4, "judge_model": "a", "seed": 7}})
    q1 = (tmp_path / "y", {"meta": {"top_k": 4, "judge_model": "b", "seed": 7}})
    assert report.not_comparable(q0, q1, quality=True) == ["judge_model"]
    assert report.not_comparable(q0, q1, quality=False) == []


def test_judge_strict_retry_and_new_rubrics():
    class Chat:
        def __init__(self, replies):
            self.replies, self.prompts = list(replies), []

        def invoke(self, p):
            self.prompts.append(p)
            return type("R", (), {"content": self.replies.pop(0)})()

    c = Chat(["not json at all", '{"abstains": true}'])
    j = Judge(chat=c)
    assert j.abstains("q", "I don't know") is True
    assert j.parse_retries == 1 and "ONLY one JSON object" in c.prompts[1]
    bad = Judge(chat=Chat(["x", "y"]))
    with pytest.raises(ValueError):
        bad.web_answer("q", "a")


def test_judge_rows_categories_and_failures():
    from eval.run import judge_rows

    class J:
        def abstains(self, q, a):
            return "know" in a

        def correctness(self, q, t, a):
            return {"score": 1, "reason": "ok"}

        def web_answer(self, q, a):
            raise RuntimeError("judge down")

        def faithfulness(self, a, ctx):
            return {"score": 0.5, "reason": ""}

    def r(cat, answer="Fact 660", **kw):
        return {
            "category": cat,
            "question": "q",
            "ground_truth": "660",
            "answer": answer,
            "abstained": False,
            "crashed": False,
            "context_available": True,
            "context_texts": ["c"],
            "correct": None,
            "web_answer": None,
            "faithfulness": None,
            **kw,
        }

    rows = [
        r("exact_term"),
        r("out_of_corpus"),
        r("unanswerable", "I don't know"),
        r("semantic", crashed=True),
        r("exact_term", context_available=False),
    ]
    judge_rows(rows, J())
    assert rows[0]["correct"] == 1 and rows[0]["faithfulness"] == 0.5
    assert rows[1]["web_answer"] is None and "judge down" in rows[1]["judge_error"]
    assert rows[2]["abstained"] is True and rows[2]["correct"] is None  # abstention only
    assert rows[3]["correct"] == 0
    assert rows[4]["faithfulness"] is None  # context unavailable: not faked
    a = metrics.aggregate(rows)
    assert a["judge_failures"] == 1 and a["web_answer_rate"] is None


def test_provider_calls_and_clean_among_faulted():
    rows = [
        row(faults=[["chat", "429"]], provider_calls={"chat": 2, "structured": 3, "embed": 1}),
        row(
            faults=[["chat", "429"]],
            degraded=True,
            provider_calls={"chat": 0, "structured": 1, "embed": 1},
        ),
        row(provider_calls={"chat": 1}),
    ]
    a = metrics.aggregate(rows)
    assert a["clean_among_faulted"] == 0.5
    assert a["mean_provider_llm_calls"] == pytest.approx((5 + 1 + 1) / 3)
    assert a["mean_provider_embed"] == pytest.approx(2 / 3)
    assert a["mean_logical_llm_calls"] == 3  # row() sets llm_calls=3


def test_hermetic_blocks_gethostbyname_and_getnameinfo():
    import socket

    from eval.hermetic import block_network

    seen: list[str] = []
    with block_network(seen):
        for fn, arg in (
            (socket.gethostbyname, "example.com"),
            (socket.gethostbyname_ex, "example.org"),
        ):
            with pytest.raises(ConnectionError):
                fn(arg)
        with pytest.raises(ConnectionError):
            socket.getnameinfo(("93.184.216.34", 80), 0)
    assert seen == ["example.com", "example.org", "93.184.216.34"]


def test_stratified_limit_round_robin():
    from eval.dataset import stratified_limit

    rows = [{"id": f"{c}{i}", "category": c} for c in "ab" for i in range(3)] + [
        {"id": "c0", "category": "c"}
    ]
    assert [r["id"] for r in stratified_limit(rows, 4)] == ["a0", "b0", "c0", "a1"]
    assert len(stratified_limit(rows, 99)) == 7
    assert stratified_limit(rows, 4) == stratified_limit(rows, 4)  # deterministic
    with pytest.raises(ValueError):
        stratified_limit(rows, 0)


def test_limit_zero_is_an_error():
    from eval.run import main

    assert main(["--system", "v1", "--suite", "chaos", "--offline", "--limit", "0"]) == 2


def test_judge_strict_retry_also_retries_transient(monkeypatch):
    import tenacity

    monkeypatch.setattr(tenacity.nap.time, "sleep", lambda _s: None)  # restored after the test

    class Chat:
        def __init__(self):
            self.replies = [
                "garbage",
                Exception("[503] unavailable"),
                '{"abstains": false}',
            ]

        def invoke(self, _p):
            r = self.replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return type("R", (), {"content": r})()

    j = Judge(chat=Chat(), max_attempts=3)
    assert j.abstains("q", "a") is False and j.parse_retries == 1


def test_web_answer_judge_failures_counted_not_in_denominator():
    rows = [
        row(category="out_of_corpus", web_answer=1),
        row(category="out_of_corpus", web_answer=None, judge_error="RuntimeError: down"),
        row(category="out_of_corpus", web_answer=0),
    ]
    a = metrics.aggregate(rows)
    assert a["web_answer_rate"] == 0.5 and a["web_answer_judge_failures"] == 1


@pytest.mark.parametrize(
    "row, expected",
    [
        ({"errors": ["web search failed: DDGSException: No results found."]}, True),
        ({"errors": ["web search skipped: circuit breaker open"]}, True),
        ({"crashed": True, "exception": "DDGSException: No results found."}, True),
        ({"crashed": True, "exception": "TimeoutError"}, False),
        ({"errors": []}, False),
        ({}, False),
    ],
)
def test_web_unavailable(row, expected):
    assert metrics.web_unavailable(row) is expected


def _run(tmp_path, name, grader, rows=None, **meta):
    base = {
        "system": "v1",
        "suite": "quality",
        "mode": "live",
        "rate": None,
        "seed": 7,
        "n_rows": 1,
        "corpus_hash": "c",
        "eval_set_hash": "e",
        "top_k": 4,
        "judge_model": "j",
        "grader_model": grader,
        "timestamp_utc": "2026-01-01T00:00:00+00:00",
        "src_tree_hash": "s",
        "llm_model": "g",
    }
    base.update(meta)
    if rows is None:
        rows = [{"errors": ["web search skipped: circuit breaker open"]}]
    d = {"meta": base, "aggregates": {"correctness": 0.5}, "rows": rows}
    p = tmp_path / name
    p.write_text(json.dumps(d), encoding="utf-8")
    return p, d


DOWN = {"errors": ["web search failed: DDGSException"], "expected_route": "local"}
UP = {"errors": [], "expected_route": "local"}


def test_ablation_section_and_web_rate_fallback(tmp_path):
    abl_dir = tmp_path / "_ablation"
    abl_dir.mkdir()
    main = _run(tmp_path, "main.json", "small", rows=[DOWN, DOWN])
    _run(abl_dir, "abl.json", "big", rows=[DOWN, UP])
    out = "\n".join(report.ablation_section(main, abl_dir))
    assert "grader `small` (default)" in out and "grader `big`" in out
    # the metric is missing from aggregates, so each side is computed from its own rows
    assert "| Web search unavailable | 100.0% | 50.0% |" in out
    assert "confounded by the outage" in out


@pytest.mark.parametrize("field", ["eval_set_hash", "src_tree_hash", "llm_model"])
def test_ablation_not_comparable(tmp_path, field):
    abl_dir = tmp_path / "_ablation"
    abl_dir.mkdir()
    main = _run(tmp_path, "main.json", "small")
    _run(abl_dir, "abl.json", "big", **{field: "other"})
    out = report.ablation_section(main, abl_dir)
    assert any(f"not comparable: {field}" in s for s in out)


def test_ablation_absent_renders_nothing(tmp_path):
    main = _run(tmp_path, "main.json", "small")
    assert report.ablation_section(main, tmp_path / "missing") == []


def test_web_note(tmp_path):
    up = _run(tmp_path, "a.json", "x", rows=[UP])
    down = _run(tmp_path, "b.json", "x", rows=[DOWN, UP])
    assert report.web_note({"v0": up, "v1": up}) == []
    note = report.web_note({"v0": up, "v1": down})[0]
    assert "(v1 50.0% of questions)" in note and "(v1 1)" in note


def test_meta_block_offline_says_fakes(tmp_path):
    run = _run(tmp_path, "c.json", "x", suite="chaos", mode="offline", rate=0.1)
    lines = report.meta_block({("v1", "chaos", "offline", 0.1): run})
    assert "fakes (configured names not called)" in lines[-1] and "`g`" not in lines[-1]
