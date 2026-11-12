"""Run the copilot eval over the fictional example corpus.

    python -m eval.run --offline                  # fakes; no key; plumbing check, NOT quality
    python -m eval.run --update-results           # live (needs the key); rewrites eval/RESULTS.md

Metrics: attribution-error rate and length-compliance rate on the final answers, coverage-detection
accuracy (fast and graded) against the `in_kb` labels, and a judge-model grounding score (judge
model differs from the generator). Result JSON goes to the git-ignored `eval/results/`; only a live
run may rewrite the curated `eval/RESULTS.md`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from copilot.answer import attribution_violations, generate_answer, length_violation
from copilot.config import ROOT, Settings
from copilot.engine import ground
from copilot.ingest import build_index, known_labels

from .judge import DEFAULT_JUDGE_MODEL, Judge, make_judge

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
QUESTIONS = EVAL_DIR / "questions.jsonl"
EXAMPLES = ROOT / "examples"


def load_questions(path: Path = QUESTIONS) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _sha(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def _rate(flags: list[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def evaluate(
    settings: Settings, questions: list[dict[str, Any]], judge: Judge | None = None
) -> dict[str, Any]:
    """Index the corpus in `settings`, then score every question. Returns a JSON-able dict."""
    build_index(settings)
    known = known_labels(settings)
    rows: list[dict[str, Any]] = []
    for q in questions:
        text = q["question"]
        fast = ground(text, grade=False, settings=settings)
        graded = ground(text, grade=True, settings=settings)
        res = generate_answer(
            text, fast, length=q["length"], settings=settings, all_labels=known
        )
        row: dict[str, Any] = {
            "id": q["id"],
            "in_kb": q["in_kb"],
            "covered_fast": fast.covered,
            "covered_graded": graded.covered,
            "labels_used": res.labels_used,
            "retries": res.retries,
            "warnings": res.warnings,
            "attribution_error": bool(
                attribution_violations(res.text, res.labels_used, known, user_text=text)
            ),
            "length_ok": length_violation(res.text, q["length"]) is None,
            "generated": bool(res.text),
            "grounding": None,
            # kept so a judge outage can be re-scored without regenerating
            "answer": res.text,
            "context": fast.context,
        }
        if judge and q["in_kb"] and res.text:
            try:
                row["grounding"] = judge.grounding(res.text, fast.context)
            except Exception as exc:  # judge faults are reported, not fatal
                row["judge_error"] = f"{type(exc).__name__}: {exc}"[:200]
        rows.append(row)

    scored = [r for r in rows if r["generated"]]
    grounded = [r["grounding"] for r in rows if r["grounding"] is not None]
    metrics = {
        "n": len(rows),
        "n_generated": len(scored),
        "attribution_error_rate": _rate([r["attribution_error"] for r in scored]),
        "length_compliance_rate": _rate([r["length_ok"] for r in scored]),
        "regeneration_rate": _rate([r["retries"] > 0 for r in scored]),
        "coverage_accuracy_fast": _rate([r["covered_fast"] == r["in_kb"] for r in rows]),
        "coverage_accuracy_graded": _rate([r["covered_graded"] == r["in_kb"] for r in rows]),
        "grounding_mean": sum(grounded) / len(grounded) if grounded else None,
        "n_judged": len(grounded),
    }
    return {"metrics": metrics, "rows": rows}


def render_results(result: dict[str, Any]) -> str:
    """Markdown for the curated RESULTS.md (live runs only)."""
    m, meta = result["metrics"], result["meta"]

    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{x * 100:.0f}%"

    tried = [r for r in result.get("rows", []) if r.get("in_kb") and r.get("generated")]
    failed = sum(1 for r in tried if r.get("judge_error"))
    grounding = pct(m["grounding_mean"])
    if m["n_judged"] == 0 and failed:  # never print a score the judge did not give
        grounding = f"not measured: the judge call failed for {failed} of {len(tried)} attempts"

    return f"""# Copilot eval results

Measured by `python -m eval.run --update-results` on {meta['time_utc']} (commit `{meta['commit']}`).

**Limits:** {m['n']} questions over a fictional 2-employer corpus, so one question moves a rate by
about {round(100 / max(m['n'], 1))} points. Coverage accuracy is scored against hand labels
(`in_kb`).
The judge is one model; grounding is a noisy signal. Not a benchmark.

| Metric | Value |
|---|---|
| Attribution-error rate (final answers) | {pct(m['attribution_error_rate'])} |
| Length-compliance rate (final answers) | {pct(m['length_compliance_rate'])} |
| Answers needing a regeneration | {pct(m['regeneration_rate'])} |
| Coverage-detection accuracy, fast mode | {pct(m['coverage_accuracy_fast'])} |
| Coverage-detection accuracy, graded mode | {pct(m['coverage_accuracy_graded'])} |
| Grounding (judge, in-KB answers, n={m['n_judged']}) | {grounding} |

Models: answer `{meta['answer_model']}`, grader `{meta['grader_model']}`,
judge `{meta['judge_model']}`, embeddings `nvidia/nemotron-3.5-embed-1b`.
Corpus hash `{meta['corpus_hash']}`, question-set hash
`{meta['questions_hash']}`. Result file: `results/{meta['file']}`.
"""


def _commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT,
            timeout=10,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="eval.run", description=__doc__.split("\n\n")[0])
    p.add_argument("--offline", action="store_true", help="fake models/embeddings; no key needed")
    p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    p.add_argument("--update-results", action="store_true", help="live only: rewrite RESULTS.md")
    args = p.parse_args(argv)
    if args.offline and args.update_results:
        print("--update-results needs a live run (offline is never published)", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="copilot_eval_", ignore_cleanup_errors=True) as tmp:
        base: dict[str, Any] = {
            "corpus_dir": str(EXAMPLES / "corpus"),
            "persist_dir": str(Path(tmp) / "index"),
            "persona_path": str(EXAMPLES / "persona.md"),
            "style_path": str(EXAMPLES / "style_examples.md"),
        }
        if args.offline:
            from crag.llm import reset_factories

            from .fakes import install, stub_handler

            # hash-embedding cosine is meaningless, so the dense veto is off offline
            settings = Settings(_env_file=None, dense_threshold=0.0, **base)
            install(stub_handler)
            judge = None
        else:
            settings = Settings(**base)
            if not settings.key_configured:
                print("NVIDIA_API_KEY missing or placeholder; live eval needs it.", file=sys.stderr)
                return 2
            judge = make_judge(settings, args.judge_model)
        try:
            result = evaluate(settings, load_questions(), judge)
        finally:
            if args.offline:
                reset_factories()

    now = datetime.now(timezone.utc)
    mode = "offline" if args.offline else "live"
    RESULTS_DIR.mkdir(exist_ok=True)
    fname = f"{mode}_{now:%Y%m%dT%H%M%SZ}.json"
    result["meta"] = {
        "mode": mode,
        "time_utc": now.strftime("%Y-%m-%d %H:%M"),
        "commit": _commit(),
        "answer_model": settings.answer_model,
        "grader_model": settings.grader_model,
        "judge_model": None if args.offline else args.judge_model,
        "corpus_hash": _sha([f for f in (EXAMPLES / "corpus").rglob("*") if f.is_file()]),
        "questions_hash": _sha([QUESTIONS]),
        "file": fname,
    }
    (RESULTS_DIR / fname).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["metrics"], indent=2))
    if args.offline:
        print("OFFLINE: stub generator and hash embeddings; plumbing check only, not quality.")
    elif args.update_results:
        (EVAL_DIR / "RESULTS.md").write_text(render_results(result), encoding="utf-8")
        print("RESULTS.md updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
