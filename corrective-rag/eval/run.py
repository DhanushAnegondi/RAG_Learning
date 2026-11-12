"""CLI: run one system (v0|v1) on the eval set and write a provenance-stamped result JSON.

    python -m eval.run --system v0 --src <v0 src> --suite chaos --offline --rate 0.3 --seed 7
    python -m eval.run --system v1 --suite quality

One system per process (both packages are named `crag`). Result files are git-ignored; only the
curated `eval/RESULTS.md` (see report.py) is committed.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import metrics
from .chaos import FaultInjector, install
from .dataset import CORPUS_DIR, EVAL_SET, corpus_hash, file_sha256, load_eval_set, stratified_limit
from .hermetic import block_network
from .judge import DEFAULT_JUDGE_MODEL, Judge, key_fact_match
from .systems import RunResult, V0System, V1System

RESULTS_DIR = Path(__file__).resolve().parent / "results"
ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
PLACEHOLDER = "PASTE_"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="eval.run", description=__doc__.split("\n\n")[0])
    p.add_argument("--system", choices=("v0", "v1"), required=True)
    p.add_argument("--src", help="v0 only: path to the baseline `src` directory (contains crag/)")
    p.add_argument("--suite", choices=("quality", "chaos"), required=True)
    p.add_argument(
        "--offline", action="store_true", help="fake LLM/embeddings/web; no key; chaos only"
    )
    p.add_argument(
        "--rate", type=float, default=0.3, help="chaos: per-provider-call fault probability"
    )
    p.add_argument(
        "--rates", help="chaos sweep, comma-separated, e.g. 0,0.05,0.1,0.3 (one file each)"
    )
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--limit", type=int, help="N rows, round-robin across categories (>= 1)")
    p.add_argument("--grader-model", help="v1 only: override the relevance-grader model (ablation)")
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    p.add_argument("--ragas", action="store_true", help="optional ragas metrics if installed")
    return p.parse_args(argv)


def load_key() -> str | None:
    """NVIDIA key from the environment or the repo-root .env; None if absent or PASTE_*."""
    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key and ROOT_ENV.exists():
        from dotenv import dotenv_values

        key = dotenv_values(ROOT_ENV).get("NVIDIA_API_KEY") or ""
    key = key.strip()
    return key if key and not key.startswith(PLACEHOLDER) else None


def make_system(args: argparse.Namespace) -> Any:
    if args.system == "v0":
        if not args.src:
            raise SystemExit("--src is required for --system v0")
        return V0System(args.src)
    overrides: dict[str, Any] = {}
    if args.offline:
        overrides["backoff_base_s"] = 0.0  # retries are real, only the waiting is skipped
    if args.grader_model:
        overrides["grader_model"] = args.grader_model  # ablation: e.g. the 70B model v0 used
    return V1System(**overrides)


def score_rows(rows: list[dict], results: list[RunResult], faults: dict[str, list]) -> list[dict]:
    from .metrics import evidence_rank

    scored = []
    for row, res in zip(rows, results, strict=True):
        d = dataclasses.asdict(res)
        d.update(
            category=row["category"],
            expected_route=row["expected_route"],
            evidence=row["evidence"],
            question=row["question"],
            ground_truth=row["ground_truth"],
            faults=[list(f) for f in faults.get(row["id"], [])],
            rank=evidence_rank(row["evidence"], res.retrieved_texts),
            correct=None,
            web_answer=None,
            key_fact=None,
            faithfulness=None,
            judge_reason=None,
            judge_error=None,
            abstained_structural=res.abstained,  # v1 flag / v0 regex: secondary to the judge
            abstained_judge=None,
        )
        scored.append(d)
    return scored


IN_CORPUS = ("exact_term", "semantic")


def judge_rows(scored: list[dict], judge: Judge) -> None:
    """Fill the judge-derived fields (live runs only; the judge is never fault-injected).

    Headline correctness covers in-corpus rows only. out_of_corpus rows get `web_answer`;
    unanswerable rows are scored by abstention alone. A failed judge call leaves the field None and
    records `judge_error` on the row: it is counted and reported, never silently dropped."""
    for d in scored:
        errors: list[str] = []

        def attempt(fn: Any, *args: Any, errors: list[str] = errors) -> Any:
            try:
                return fn(*args)
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}"[:120])
                return None

        cat = d["category"]
        if d["crashed"]:
            d["abstained"] = False
            if cat in IN_CORPUS:
                d["correct"] = 0
            elif cat == "out_of_corpus":
                d["web_answer"] = 0
            continue
        verdict = attempt(judge.abstains, d["question"], d["answer"])
        if verdict is not None:
            d["abstained_judge"] = d["abstained"] = bool(verdict)
        if cat in IN_CORPUS:
            d["key_fact"] = key_fact_match(d["ground_truth"], d["answer"])
            if d["abstained"]:
                d["correct"] = 0
            else:
                j = attempt(judge.correctness, d["question"], d["ground_truth"], d["answer"])
                if j:
                    d["correct"], d["judge_reason"] = j["score"], j["reason"]
        elif cat == "out_of_corpus":
            if d["abstained"]:
                d["web_answer"] = 0
            else:
                j = attempt(judge.web_answer, d["question"], d["answer"])
                if j:
                    d["web_answer"], d["judge_reason"] = j["score"], j["reason"]
        if not d["abstained"] and d["context_available"]:
            f = attempt(judge.faithfulness, d["answer"], d["context_texts"])
            if f:
                d["faithfulness"] = f["score"]
        d["judge_error"] = "; ".join(errors) or None


def run_ragas(scored: list[dict], model: str) -> dict[str, Any]:
    """Optional extra. Imported lazily; any failure is recorded, not raised."""
    try:
        import ragas  # noqa: F401
    except ImportError:
        print("note: --ragas requested but ragas is not installed (eval/requirements.txt); skipped")
        return {"status": "skipped: ragas not installed"}
    try:
        from datasets import Dataset
        from langchain_nvidia_ai_endpoints import ChatNVIDIA, NVIDIAEmbeddings
        from ragas import evaluate
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics import faithfulness

        use = [d for d in scored if not d["crashed"] and not d["abstained"] and d["context_texts"]]
        ds = Dataset.from_dict(
            {
                "user_input": [d["question"] for d in use],
                "response": [d["answer"] for d in use],
                "retrieved_contexts": [d["context_texts"] for d in use],
            }
        )
        out = evaluate(
            ds,
            metrics=[faithfulness],
            llm=LangchainLLMWrapper(ChatNVIDIA(model=model, temperature=0)),
            embeddings=LangchainEmbeddingsWrapper(NVIDIAEmbeddings()),
        )
        return {
            "status": "ok",
            "n": len(use),
            "scores": {k: float(v) for k, v in out._repr_dict.items()},
        }
    except Exception as exc:
        return {"status": f"failed: {type(exc).__name__}: {exc}"[:300]}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit is not None and args.limit < 1:
        print("error: --limit must be >= 1", file=sys.stderr)
        return 2
    live = not args.offline
    if args.offline and args.suite != "chaos":
        print(
            "error: --offline is only meaningful for --suite chaos (quality needs a real model)",
            file=sys.stderr,
        )
        return 2
    if live and not load_key():
        print(
            "error: NVIDIA_API_KEY is not configured (missing or a PASTE_* placeholder in the "
            "repo-root "
            ".env). Live runs need it; use --suite chaos --offline for a keyless run.",
            file=sys.stderr,
        )
        return 2
    if live:
        os.environ["NVIDIA_API_KEY"] = load_key() or ""
    else:
        os.environ.pop("NVIDIA_API_KEY", None)

    rows = load_eval_set()
    if args.limit is not None:
        rows = stratified_limit(rows, args.limit)
    rates = parse_rates(args)
    system = make_system(args)
    leaks: list[str] = []
    net = block_network(leaks) if args.offline else contextlib.nullcontext()
    with net:
        system.prepare()
        inj = FaultInjector(rates[0] or 0.0, args.seed)
        # Quality runs install the layer at rate 0: no faults, but every provider call is counted.
        chaos_ctx = install(args.system, inj, offline=args.offline)
        with chaos_ctx:
            system.build()
            sweeps = []
            for rate in rates:
                inj.rate = rate or 0.0
                system.reset()
                sweeps.append((rate, *run_rows(system, inj, rows)))
    if leaks:
        print(
            f"WARNING: {len(leaks)} blocked network attempts: {sorted(set(leaks))}", file=sys.stderr
        )
    for rate, results, faults, runtime in sweeps:
        path = write_result(args, system, rows, rate, results, faults, runtime, leaks)
        print(f"wrote {path}")
    return 0


def parse_rates(args: argparse.Namespace) -> list[float | None]:
    if args.suite != "chaos":
        return [None]
    if args.rates:
        return [float(x) for x in args.rates.split(",")]
    return [args.rate]


def run_rows(
    system: Any, inj: FaultInjector, rows: list[dict]
) -> tuple[list[RunResult], dict[str, list], float]:
    results: list[RunResult] = []
    faults: dict[str, list] = {}
    t0 = time.perf_counter()
    for i, row in enumerate(rows, 1):
        inj.begin(row["id"])
        res = system.run(row["id"], row["question"])
        faults[row["id"]] = inj.end()
        res.provider_calls = dict(inj.calls)
        results.append(res)
        tag = "CRASH" if res.crashed else ("abstain" if res.abstained else res.route)
        print(
            f"[{i:02d}/{len(rows)}] {row['id']} {tag:8s} faults={len(faults[row['id']])}",
            flush=True,
        )
    return results, faults, time.perf_counter() - t0


def write_result(
    args: argparse.Namespace,
    system: Any,
    rows: list[dict],
    rate: float | None,
    results: list[RunResult],
    faults: dict[str, list],
    runtime_s: float,
    leaks: list[str],
) -> Path:
    live = not args.offline
    scored = score_rows(rows, results, faults)
    judge: Judge | None = None
    if live:  # judging happens after the chaos patches are gone, so it is never fault-injected
        judge = Judge(args.judge_model)
        judge_rows(scored, judge)
    ragas_out = run_ragas(scored, args.judge_model) if args.ragas else None
    desc = system.describe()
    k = desc.get("top_k", 4)
    now = datetime.now(timezone.utc)
    mode = "offline" if args.offline else "live"
    meta = {
        "system": args.system,
        "suite": args.suite,
        "mode": mode,
        "timestamp_utc": now.isoformat(timespec="seconds"),
        **desc,
        "judge_model": args.judge_model if live else None,
        "corpus_hash": corpus_hash(CORPUS_DIR),
        "eval_set_hash": file_sha256(EVAL_SET),
        "n_rows": len(rows),
        "rate": rate,
        "seed": args.seed,
        "runtime_s": round(runtime_s, 1),
        "src": args.src if args.system == "v0" else None,
        "grader_override": args.grader_model,
        "judge_parse_retries": judge.parse_retries if judge else None,
        "network_blocked": args.offline,
        "network_attempts": sorted(set(leaks)) if args.offline else None,
    }
    out = {
        "meta": meta,
        "aggregates": metrics.aggregate(scored, k),
        "by_category": metrics.by_category(scored, k),
        "rows": scored,
    }
    if ragas_out is not None:
        out["ragas"] = ragas_out
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tag = "" if rate is None else f"_r{rate:g}"
    stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    path = RESULTS_DIR / f"{args.system}_{args.suite}_{mode}{tag}_{stamp}.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
