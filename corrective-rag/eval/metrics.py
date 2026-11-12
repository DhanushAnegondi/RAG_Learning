"""Pure metric math over per-row results. No LLM, no I/O: unit-tested offline.

A "scored row" is a dict: the eval row's fields plus the system's `RunResult` fields plus
`rank` (see `evidence_rank`) and optional judge fields `correct`, `key_fact`, `faithfulness`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

_WS = re.compile(r"\s+")


def norm(text: str) -> str:
    """Lower-case and collapse whitespace so evidence survives re-chunking and line wraps."""
    return _WS.sub(" ", text).strip().lower()


def evidence_rank(evidence: Sequence[str], texts: Sequence[str]) -> int | None:
    """1-based rank at which ALL evidence substrings are present in the top-r chunks (union).

    Single-evidence rows reduce to "rank of the first chunk containing it". Multi-evidence rows may
    split their facts across adjacent chunks, so the union is used. None when never complete."""
    if not evidence:
        return None
    need = [norm(e) for e in evidence]
    seen = ""
    for r, text in enumerate(texts, 1):
        seen += " " + norm(text)
        if all(e in seen for e in need):
            return r
    return None


def _mean(xs: Iterable[float]) -> float | None:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile, q in [0, 100]."""
    if not values:
        return None
    s = sorted(values)
    pos = (len(s) - 1) * q / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def hit_at_k(ranks: Sequence[int | None], k: int) -> float | None:
    """Fraction of evidence-bearing rows whose evidence is complete within the top k."""
    return _mean(1.0 if r is not None and r <= k else 0.0 for r in ranks)


def mrr(ranks: Sequence[int | None]) -> float | None:
    """Mean reciprocal rank (0 when the evidence was never retrieved)."""
    return _mean(1.0 / r if r else 0.0 for r in ranks)


def effective_route(row: dict) -> str:
    """What the user saw: an abstention is 'abstain' regardless of which path produced it."""
    if row.get("crashed"):
        return "crash"  # a crashed question never routed anywhere; it must not match "local"
    return "abstain" if row.get("abstained") else row.get("route", "local")


def route_matches(expected: str, actual: str, *, lenient: bool) -> bool:
    if actual == expected:
        return True
    # lenient: a local+web answer is accepted where either local or web was expected
    return lenient and actual == "local+web" and expected in ("local", "web")


def _provider(r: dict, channel: str) -> int:
    return int((r.get("provider_calls") or {}).get(channel, 0))


def _answered(r: dict) -> bool:
    """Completed without crashing and returned a non-empty, non-abstaining answer."""
    return (
        not r.get("crashed") and not r.get("abstained") and bool(str(r.get("answer", "")).strip())
    )


def _abstained_ok(r: dict) -> bool:
    return not r.get("crashed") and bool(r.get("abstained"))


def web_unavailable(r: dict) -> bool:
    """The web search this question needed failed or was skipped (v1 records it as an error, v0
    crashes with the search library's exception). Live DuckDuckGo is free and unreliable, so runs
    must show how often it was down before web-dependent numbers are read as quality."""
    errs = " ".join(str(e) for e in (r.get("errors") or []))
    if "web search failed" in errs or "web search skipped" in errs:
        return True
    return bool(r.get("crashed")) and "DDGS" in str(r.get("exception") or "")


def recovery_rate(rows: Sequence[dict]) -> dict[str, Any]:
    """Error recovery rate = faulted questions that finished without crashing AND returned a usable
    answer or an explicit abstain, divided by faulted questions."""
    faulted = [r for r in rows if r.get("faults")]
    recovered = [
        r
        for r in faulted
        if not r.get("crashed") and (r.get("abstained") or str(r.get("answer", "")).strip())
    ]
    return {
        "faulted_questions": len(faulted),
        "recovered": len(recovered),
        "rate": len(recovered) / len(faulted) if faulted else None,
    }


def aggregate(rows: Sequence[dict], k: int = 4) -> dict[str, Any]:
    """All headline numbers for one set of scored rows. None means 'no rows to measure'."""
    ev_ranks = [r.get("rank") for r in rows if r.get("evidence")]
    exp = [r for r in rows if r.get("expected_route")]
    unans = [r for r in rows if r.get("category") == "unanswerable"]
    in_corpus = [r for r in rows if r.get("expected_route") == "local"]
    lat = [r["latency_ms"] for r in rows if r.get("latency_ms") is not None]
    faulted = [r for r in rows if r.get("faults")]
    judged = [r["correct"] for r in rows if r.get("correct") is not None]
    out: dict[str, Any] = {
        "n": len(rows),
        "k": k,
        "n_with_evidence": len(ev_ranks),
        "hit_at_1": hit_at_k(ev_ranks, 1),
        f"hit_at_{k}": hit_at_k(ev_ranks, k),
        "mrr": mrr(ev_ranks),
        "routing_exact": _mean(
            route_matches(r["expected_route"], effective_route(r), lenient=False) for r in exp
        ),
        "routing_lenient": _mean(
            route_matches(r["expected_route"], effective_route(r), lenient=True) for r in exp
        ),
        "abstention_accuracy": _mean(1.0 if r.get("abstained") else 0.0 for r in unans),
        "false_abstention_rate": _mean(1.0 if r.get("abstained") else 0.0 for r in in_corpus),
        "crash_rate": _mean(1.0 if r.get("crashed") else 0.0 for r in rows),
        "latency_p50_ms": percentile(lat, 50),
        "latency_p95_ms": percentile(lat, 95),
        "mean_logical_llm_calls": _mean(
            r["llm_calls"] for r in rows if r.get("llm_calls") is not None
        ),
        "mean_provider_llm_calls": _mean(
            _provider(r, "chat") + _provider(r, "structured") for r in rows
        ),
        "mean_provider_chat": _mean(_provider(r, "chat") for r in rows),
        "mean_provider_structured": _mean(_provider(r, "structured") for r in rows),
        "mean_provider_embed": _mean(_provider(r, "embed") for r in rows),
        "mean_provider_web": _mean(_provider(r, "web") for r in rows),
        "web_answer_rate": _mean(r["web_answer"] for r in rows if r.get("web_answer") is not None),
        "clean_among_faulted": _mean(
            1.0 if _answered(r) and not r.get("degraded") else 0.0 for r in faulted
        ),
        "web_answer_judge_failures": sum(
            1
            for r in rows
            if r.get("category") == "out_of_corpus"
            and r.get("web_answer") is None
            and r.get("judge_error")
        ),
        "judge_failures": sum(1 for r in rows if r.get("judge_error")),
        "web_unavailable_rate": _mean(1.0 if web_unavailable(r) else 0.0 for r in rows),
        "abstention_accuracy_structural": _mean(
            1.0 if r.get("abstained_structural") else 0.0
            for r in unans
            if "abstained_structural" in r
        ),
        "false_abstention_rate_structural": _mean(
            1.0 if r.get("abstained_structural") else 0.0
            for r in in_corpus
            if "abstained_structural" in r
        ),
        "correctness": _mean(judged),
        "key_fact_match": _mean(r["key_fact"] for r in rows if r.get("key_fact") is not None),
        "faithfulness": _mean(r["faithfulness"] for r in rows if r.get("faithfulness") is not None),
        "faulted_questions": len(faulted),
        "answered_rate": _mean(1.0 if _answered(r) else 0.0 for r in rows),
        "abstain_rate": _mean(1.0 if _abstained_ok(r) else 0.0 for r in rows),
        "degraded_rate": _mean(1.0 if r.get("degraded") else 0.0 for r in rows),
        "mean_retries": _mean(r.get("retries", 0) for r in rows),
    }
    rec = recovery_rate(rows)
    out["error_recovery_rate"] = rec["rate"]
    out["recovered"] = rec["recovered"]
    fj = [r["correct"] for r in faulted if r.get("correct") is not None]
    out["correct_under_fault"] = _mean(fj)
    return out


def by_category(rows: Sequence[dict], k: int = 4) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["category"]].append(r)
    return {cat: aggregate(rs, k) for cat, rs in sorted(groups.items())}
