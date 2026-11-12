# ruff: noqa: E501  (prose and prompt text)
"""Render `eval/RESULTS.md` from the latest result file per (system, suite, mode).

Only numbers present in a result file are printed; a missing run is shown as "not run". Nothing is
interpolated or estimated.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .metrics import web_unavailable

RESULTS_DIR = Path(__file__).resolve().parent / "results"
ABLATION_DIR = RESULTS_DIR / "_ablation"
OUT = Path(__file__).resolve().parent / "RESULTS.md"
SYSTEMS = ("v0", "v1")
NOT_RUN = "not run"

QUALITY_ROWS = [
    ("Retrieval hit@1", "hit_at_1", "pct"),
    ("Retrieval hit@k", "hit_at_k", "pct"),
    ("MRR", "mrr", "num"),
    ("Answer correctness, exact_term + semantic (LLM judge)", "correctness", "pct"),
    ("Key-fact match, exact_term + semantic (deterministic)", "key_fact_match", "pct"),
    ("Web answer rate, out_of_corpus (LLM judge)", "web_answer_rate", "pct"),
    ("Web answer judge failures (excluded from the rate)", "web_answer_judge_failures", "int"),
    ("Faithfulness (LLM judge)", "faithfulness", "pct"),
    ("Routing accuracy (exact)", "routing_exact", "pct"),
    ("Routing accuracy (lenient)", "routing_lenient", "pct"),
    ("Abstention accuracy, unanswerable (judge-assisted)", "abstention_accuracy", "pct"),
    ("False-abstention rate, in-corpus (judge-assisted)", "false_abstention_rate", "pct"),
    ("Abstention accuracy, structural flag/regex", "abstention_accuracy_structural", "pct"),
    ("False-abstention rate, structural flag/regex", "false_abstention_rate_structural", "pct"),
    ("Crash rate", "crash_rate", "pct"),
    ("Web search unavailable (failed or skipped), share of q", "web_unavailable_rate", "pct"),
    ("Judge failures (rows)", "judge_failures", "int"),
    ("Latency p50 (ms)", "latency_p50_ms", "ms"),
    ("Latency p95 (ms)", "latency_p95_ms", "ms"),
    ("Provider LLM calls / q (chat + structured, every attempt)", "mean_provider_llm_calls", "num"),
    ("Provider embedding calls / q", "mean_provider_embed", "num"),
    ("Logical LLM calls / q (v1 only)", "mean_logical_llm_calls", "num"),
]
# Robustness only: retrieval/routing numbers are meaningless when rows crash, so they are not shown.
CHAOS_COLS = [
    ("Faulted q", "faulted_questions", "int"),
    ("Recovery rate", "error_recovery_rate", "pct"),
    ("Clean among faulted", "clean_among_faulted", "pct"),
    ("Crash rate", "crash_rate", "pct"),
    ("Answered", "answered_rate", "pct"),
    ("Abstained", "abstain_rate", "pct"),
    ("Degraded", "degraded_rate", "pct"),
    ("Retries / q", "mean_retries", "num"),
    ("Provider LLM calls / q", "mean_provider_llm_calls", "num"),
    ("Embed calls / q", "mean_provider_embed", "num"),
    ("Logical LLM calls / q (v1)", "mean_logical_llm_calls", "num"),
]
GATE_COMMON = ("corpus_hash", "eval_set_hash", "n_rows", "seed", "rate")
GATE_QUALITY = ("top_k", "judge_model")
ABLATION_GATE = ("src_tree_hash", "llm_model", "embed_model", "fallback_models")
CATEGORY_METRICS = [
    ("hit@k", "hit_at_k", "pct"),
    ("MRR", "mrr", "num"),
    ("correct", "correctness", "pct"),
    ("routing", "routing_exact", "pct"),
    ("abstained", "abstention_accuracy", "pct"),
]


def fmt(v: Any, kind: str) -> str:
    if v is None:
        return "n/a"
    return (
        {"pct": f"{v * 100:.1f}%", "num": f"{v:.2f}", "ms": f"{v:.0f}", "int": f"{int(v)}"}[kind]
        if isinstance(v, (int, float))
        else str(v)
    )


Key = tuple[str, str, str, "float | None"]  # (system, suite, mode, chaos rate or None)


def latest_runs(results_dir: Path = RESULTS_DIR) -> dict[Key, tuple[Path, dict]]:
    """Newest file per (system, suite, mode, rate); newest by the timestamp inside the file."""
    best: dict[Key, tuple[Path, dict]] = {}
    for p in sorted(results_dir.glob("*.json")) if results_dir.exists() else []:
        d = json.loads(p.read_text(encoding="utf-8"))
        m = d["meta"]
        key = (m["system"], m["suite"], m["mode"], m.get("rate"))
        if key not in best or m["timestamp_utc"] >= best[key][1]["meta"]["timestamp_utc"]:
            best[key] = (p, d)
    return best


def _agg(run: tuple[Path, dict] | None, key: str) -> Any:
    if run is None:
        return None
    a = run[1]["aggregates"]
    if key == "web_unavailable_rate" and key not in a:  # files written before the metric existed
        rows = run[1].get("rows") or []
        return sum(web_unavailable(r) for r in rows) / len(rows) if rows else None
    return a.get(key, a.get(f"hit_at_{a.get('k', 4)}")) if key == "hit_at_k" else a.get(key)


def not_comparable(
    a: tuple[Path, dict] | None, b: tuple[Path, dict] | None, *, quality: bool
) -> list[str]:
    """Meta fields that differ between two runs. Empty list = comparable (or one side missing)."""
    if a is None or b is None:
        return []
    fields = GATE_COMMON + (GATE_QUALITY if quality else ())
    return [f for f in fields if a[1]["meta"].get(f) != b[1]["meta"].get(f)]


def compare_table(
    rows: list[tuple[str, str, str]], runs: dict[str, tuple[Path, dict] | None]
) -> list[str]:
    diff = not_comparable(runs["v0"], runs["v1"], quality=True)
    if diff:
        return [f"not comparable: {', '.join(diff)}"]
    lines = ["| Metric | v0 (before) | v1 (after) |", "|---|---|---|"]
    for label, key, kind in rows:
        cells = [NOT_RUN if runs[s] is None else fmt(_agg(runs[s], key), kind) for s in SYSTEMS]
        lines.append(f"| {label} | {cells[0]} | {cells[1]} |")
    return lines


def chaos_table(best: dict[Key, tuple[Path, dict]], mode: str) -> list[str]:
    rates = sorted({k[3] for k in best if k[1] == "chaos" and k[2] == mode and k[3] is not None})
    if not rates:
        return [f"{NOT_RUN} for either system."]
    head = ["Fault rate", "System", *[c[0] for c in CHAOS_COLS]]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rates:
        diff = not_comparable(
            best.get(("v0", "chaos", mode, r)), best.get(("v1", "chaos", mode, r)), quality=False
        )
        if diff:
            lines.append(f"| {r:g} | v0 vs v1 | not comparable: {', '.join(diff)} |")
            continue
        for s_ in SYSTEMS:
            run = best.get((s_, "chaos", mode, r))
            cells = [f"{r:g}", s_]
            if run is None:
                cells += [NOT_RUN] * len(CHAOS_COLS)
            else:
                a = run[1]["aggregates"]
                cells += [fmt(a.get(key), kind) for _, key, kind in CHAOS_COLS]
            lines.append("| " + " | ".join(cells) + " |")
    return lines


def category_table(runs: dict[str, tuple[Path, dict] | None]) -> list[str]:
    cats = sorted({c for r in runs.values() if r for c in r[1]["by_category"]})
    head = ["Category", *[f"{s} {lab}" for s in SYSTEMS for lab, _, _ in CATEGORY_METRICS]]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for c in cats:
        cells = [c]
        for s in SYSTEMS:
            for _, key, kind in CATEGORY_METRICS:
                if runs[s] is None:
                    cells.append(NOT_RUN)
                else:
                    b = runs[s][1]["by_category"].get(c, {})
                    v = b.get("hit_at_" + str(b.get("k", 4))) if key == "hit_at_k" else b.get(key)
                    cells.append(fmt(v, kind))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def web_note(runs: dict[str, tuple[Path, dict] | None]) -> list[str]:
    """Flag runs where the free web search was down, so web-dependent rows are not read as quality."""
    parts = []
    for s in SYSTEMS:
        v = _agg(runs[s], "web_unavailable_rate")
        if v:
            parts.append(f"{s} {fmt(v, 'pct')}")
    if not parts:
        return []
    exposed = []
    for s in SYSTEMS:
        rows = (runs[s] or (None, {}))[1].get("rows") or []
        n = sum(1 for r in rows if r.get("expected_route") == "local" and web_unavailable(r))
        if n:
            exposed.append(f"{s} {n}")
    hit = f" ({', '.join(exposed)})" if exposed else ""
    return [
        f"> Web search (DuckDuckGo, free, no key) was unavailable for part of these runs ({', '.join(parts)} "
        "of questions). v0 crashes on that; v1 records it, opens its circuit breaker and answers from "
        "local documents or abstains. Only retrieval (hit@k, MRR) is independent of the web. Crash rate, "
        "routing, correctness, abstention, web answer rate and latency all carry the outage: v0's "
        "web crashes are scored as wrong answers, and in-corpus questions with the web unavailable"
        f"{hit} lost the web fallback.",
        "",
    ]


ABLATION_ROWS = [
    ("Answer correctness", "correctness", "pct"),
    ("Key-fact match", "key_fact_match", "pct"),
    ("Faithfulness", "faithfulness", "pct"),
    ("Routing accuracy (exact)", "routing_exact", "pct"),
    ("False-abstention rate", "false_abstention_rate", "pct"),
    ("Web search unavailable", "web_unavailable_rate", "pct"),
    ("Retries / q", "mean_retries", "num"),
    ("Provider LLM calls / q", "mean_provider_llm_calls", "num"),
    ("Latency p50 (ms)", "latency_p50_ms", "ms"),
    ("Latency p95 (ms)", "latency_p95_ms", "ms"),
]


def ablation_section(
    main: tuple[Path, dict] | None, ablation_dir: Path = ABLATION_DIR
) -> list[str]:
    """v1 with its default grader vs v1 with another grader: newest file in `results/_ablation/`."""
    files = sorted(ablation_dir.glob("*.json")) if ablation_dir.exists() else []
    if main is None or not files:
        return []
    abl = (files[-1], json.loads(files[-1].read_text(encoding="utf-8")))
    out = ["## Ablation: grader model (v1 only)", ""]
    # same code and models apart from the grader; v0-vs-v1 cannot use these (its src differs)
    diff = not_comparable(main, abl, quality=True) + [
        f for f in ABLATION_GATE if main[1]["meta"].get(f) != abl[1]["meta"].get(f)
    ]
    if diff:
        return out + [f"not comparable: {', '.join(diff)}", ""]
    g0, g1 = main[1]["meta"].get("grader_model"), abl[1]["meta"].get("grader_model")
    out += [f"| Metric | grader `{g0}` (default) | grader `{g1}` |", "|---|---|---|"]
    for label, key, kind in ABLATION_ROWS:
        out.append(f"| {label} | {fmt(_agg(main, key), kind)} | {fmt(_agg(abl, key), kind)} |")
    w0, w1 = (fmt(_agg(r, "web_unavailable_rate"), "pct") for r in (main, abl))
    out += [
        "",
        f"Web was unavailable for {w0} vs {w1} of questions in these two runs, so differences of a few "
        "points in correctness or routing are within noise and confounded by the outage. The cost rows "
        "(retries, provider calls, latency) are the clearer signal of the grader choice.",
        "",
        f"Ablation file: `results/_ablation/{abl[0].name}`.",
        "",
    ]
    return out


def meta_block(best: dict[Key, tuple[Path, dict]]) -> list[str]:
    lines = [
        "| Run | Commit / dirty / src hash | Models | Corpus hash | Eval-set hash | Rate / seed | Time (UTC) | File |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for (system, suite, mode, _rate), (path, d) in sorted(
        best.items(), key=lambda kv: (kv[0][1], kv[0][2], kv[0][3] or 0.0, kv[0][0])
    ):
        m = d["meta"]
        if mode == "offline":  # configured names are recorded, but every call went to a fake
            models = "fakes (configured names not called)"
        else:
            models = f"gen `{m.get('llm_model')}`, grader `{m.get('grader_model')}`, embed `{m.get('embed_model')}`"
        if m.get("judge_model"):
            models += f", judge `{m['judge_model']}`"
        net = ", network blocked" if m.get("network_blocked") else ""
        rate = f"{m['rate']} / {m['seed']}" if m.get("rate") is not None else f"- / {m['seed']}"
        lines.append(
            f"| {system} {suite} ({mode}), n={m['n_rows']}{net} | `{str(m.get('commit'))[:10]}` "
            f"dirty={m.get('dirty')} src `{str(m.get('src_tree_hash'))[:10]}` | {models} | "
            f"`{m['corpus_hash'][:12]}` | `{m['eval_set_hash'][:12]}` | {rate} | "
            f"{m['timestamp_utc']} | `results/{path.name}` |"
        )
    return lines


CHAOS_NOTE = """> Footnote: v1's recovery rate is 100% by contract (`pipeline.answer` never raises), so it says little
> by itself. The informative columns are *clean among faulted*, *abstained* and *degraded*. v0 has no
> degraded flag (always 0%) and no retry counter.
"""

MEANINGS = """\
- **hit@k** - share of questions (that have labelled evidence) where the evidence text shows up in the
  top k retrieved chunks. Measures retrieval alone, before any LLM writes anything.
- **MRR** - mean of 1/rank of the first chunk set that contains the evidence (1.0 = always first, 0 = never found).
- **Answer correctness** - exact_term + semantic rows only. A judge model (different from the generator,
  temperature 0) checks the answer against the written ground truth; an abstention counts as wrong.
- **Web answer rate** - out_of_corpus rows only (the corpus cannot answer them; a web source should).
  A judge checks for a specific, on-topic, non-abstaining fact attributed to a web source with no
  fabrication about the fictional lender. It cannot verify the live value, so it is not "correctness".
- **Key-fact match** - deterministic check: are the numbers/identifiers from the ground truth present in the answer?
- **Faithfulness** - judge: what fraction of the answer's claims are supported by the context it was given.
- **Routing accuracy** - did the system take the expected path (local / web / abstain)? *Exact* needs an
  identical label; *lenient* also accepts `local+web` where `local` or `web` was expected. A crash is a miss.
- **Abstention accuracy** - on unanswerable questions (scored by abstention only), how often it declined
  instead of guessing. The primary figure uses one judge question for both systems ("does the answer
  decline or say it doesn't know?"); the structural variant (v1's `abstained` flag, v0's regex) is
  shown separately.
- **False-abstention rate** - on questions the corpus can answer, how often it wrongly refused.
- **Crash rate** - share of questions where the pipeline raised instead of returning something.
- **Clean among faulted** - of the faulted questions, the share that returned a real answer, not
  degraded and not an abstain. This is the informative column for v1.
- **Error recovery rate** - among questions where at least one provider fault was injected (timeout, 429,
  500, empty structured output, embeddings down, web down), the share that finished without crashing and
  returned a usable answer or an explicit abstain. The fault rate is per provider call, so a question
  that makes many calls is very likely to be hit at least once.
- **Answered / Abstained / Degraded** (chaos tables, share of all questions) - returned a real answer;
  returned an explicit "I don't know"; or finished but flagged `degraded` (a fallback or reduced path was
  used). v0 has no degraded flag, so it always shows 0%.
- **Retries / q** - provider retries per question (v0 has none). The fault-rate 0 row is the control:
  nothing is injected, so it shows whether each system works with the fakes at all.
- **Offline chaos** uses fake models and a blocked network, so it measures robustness only, never answer quality.
- **Provider LLM calls** - every chat and structured-output attempt sent to the provider, retries and
  fallbacks included, counted at the same boundary for both systems; embedding calls are counted
  separately. **Logical LLM calls** is v1's own pipeline counter (one per logical call, before retries)
  and is not comparable with v0. Latency is wall-clock p50/p95.
- **Judge failures** - rows where a judge call failed or returned unparseable JSON twice; those fields
  are left empty (not scored as 0) and counted here.
"""


def render(best: dict[Key, tuple[Path, dict]]) -> str:
    out = [
        "# Evaluation results",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by `python -m eval.report` "
        "from the latest recorded run of each (system, suite, mode). Anything not run is marked "
        f'"{NOT_RUN}"; no number here is estimated.',
        "",
        "**Limits:** the eval set has 40 questions (6 to 14 per category), so differences of a few "
        "points are within noise; per-category cells rest on very few rows.",
        "",
    ]
    runs = {s_: best.get((s_, "quality", "live", None)) for s_ in SYSTEMS}
    out += ["## Quality (live models)", ""]
    if all(r is None for r in runs.values()):
        out += [f"{NOT_RUN} for either system.", ""]
    else:
        out += compare_table(QUALITY_ROWS, runs) + [""]
        out += web_note(runs)
        out += ["### Per category", ""] + category_table(runs) + [""]
    out += ablation_section(runs["v1"])
    for mode, title in (
        ("offline", "Chaos, offline (fake models; robustness only, no answer quality)"),
        ("live", "Chaos, live (real models and web)"),
    ):
        out += [f"## {title}", "", *chaos_table(best, mode), ""]
    out += [CHAOS_NOTE]
    out += ["## Run metadata", ""] + (meta_block(best) if best else [NOT_RUN]) + [""]
    out += ["## What each metric means", "", MEANINGS]
    return "\n".join(out)


def main() -> int:
    best = latest_runs()
    OUT.write_text(render(best), encoding="utf-8")
    print(f"wrote {OUT} ({len(best)} runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
