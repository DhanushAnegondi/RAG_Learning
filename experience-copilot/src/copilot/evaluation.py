"""Live comparisons use fictional fixtures and disposable indexes, never the personal corpus."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from statistics import mean
from time import perf_counter
from uuid import uuid4

from .config import ROOT, get_settings


def load_questions(path: str) -> list[dict]:
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = set()
    for row in rows:
        if not isinstance(row.get("id"), str) or row["id"] in ids or not row.get("question"):
            raise ValueError("Every question needs a unique string id and nonempty question")
        ids.add(row["id"])
        if not isinstance(row.get("expected_sources"), list) or not all(isinstance(s, str) for s in row["expected_sources"]):
            raise ValueError("expected_sources must be a list of relative source paths")
        if not isinstance(row.get("answerable"), bool) or row["answerable"] != bool(row["expected_sources"]):
            raise ValueError("answerable must agree with expected_sources")
        if row.get("split") not in {"dev", "holdout"}:
            raise ValueError("Each question needs a dev/holdout split")
        for source in row["expected_sources"]:
            if source.startswith(("/", "\\")) or ":" in source or ".." in Path(source).parts:
                raise ValueError("Expected sources must stay inside the fixture corpus")
    if not rows:
        raise ValueError("Question set is empty")
    return rows


@contextmanager
def isolated_indexes(corpus: Path, directory: Path):
    from .retrieval_v2 import embedding_model
    changes = {"EXP_CORPUS_DIR": str(corpus), "EXP_PERSIST_DIR": str(directory / "v1"),
               "EXP_V2_PERSIST_DIR": str(directory / "v2"),
               "EXP_PERSONA": str(directory / "no-persona.md"),
               "EXP_STYLE": str(directory / "no-style.md"), "CRAG_EMBED_MODEL": embedding_model()}
    names = set(changes) | {"CRAG_CORPUS_DIR", "CRAG_PERSIST_DIR", "CRAG_RELEVANCE_THRESHOLD"}
    before = {name: os.environ.get(name) for name in names}
    os.environ.update(changes)
    try:
        yield
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def score(row: dict, result: dict, corpus: Path) -> dict:
    retrieved = []
    for doc in result.get("kept", []):
        source = doc.metadata["source"].replace("\\", "/")
        if Path(source).is_absolute():
            source = Path(source).resolve().relative_to(corpus).as_posix()
        if source not in retrieved:
            retrieved.append(source)
    expected = set(row["expected_sources"])
    ranks = [i for i, source in enumerate(retrieved, 1) if source in expected]
    error = result.get("error")
    return {"id": row["id"], "question": row["question"], "split": row["split"],
            "expected_sources": sorted(expected), "retrieved_sources": retrieved,
            "source_recall": len(expected.intersection(retrieved)) / len(expected) if expected else None,
            "reciprocal_rank": 1 / min(ranks) if ranks else (0 if expected else None),
            "expected_answerable": row["answerable"], "covered": result.get("covered", False),
            "coverage_correct": not error and result.get("covered", False) == row["answerable"],
            "error": error, "recheck_error": result.get("recheck_error"),
            "answer": result.get("answer"), "model_verified": result.get("verified")}


def summarize(rows: list[dict]) -> dict:
    positives = [r for r in rows if r["expected_answerable"]]
    negatives = [r for r in rows if not r["expected_answerable"]]
    return {"questions": len(rows), "errors": sum(bool(r["error"]) for r in rows),
            "recheck_errors": sum(bool(r.get("recheck_error")) for r in rows),
            "source_recall": mean(r["source_recall"] for r in positives) if positives else None,
            "source_mrr": mean(r["reciprocal_rank"] for r in positives) if positives else None,
            "coverage_accuracy": mean(r["coverage_correct"] for r in rows) if rows else None,
            "correct_abstention_rate": mean(r["coverage_correct"] for r in negatives) if negatives else None,
            "mean_seconds": mean(r["seconds"] for r in rows) if rows else None}


def run(args) -> int:
    rows = load_questions(args.dataset)
    corpus = (ROOT / "eval/fixtures/corpus").resolve()
    for row in rows:
        for source in row["expected_sources"]:
            if not (corpus / source).is_file():
                raise ValueError(f"Missing expected fixture source: {source}")
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be positive")
        rows = rows[:args.limit]
    if not args.live:
        print(f"Validated {len(rows)} fictional questions. No API calls or quality measurements were made.")
        print("Add --live to build isolated fixture indexes and compare retrieval + evidence coverage.")
        return 0
    if not get_settings().nvidia_api_key:
        print("NVIDIA_API_KEY is required for --live.")
        return 2
    from . import engine, ingest, pipeline, retrieval_v2
    from .answer import generate_answer
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / ("indexes-" + uuid4().hex[:10])
    report = {"kind": "live-fictional-fixture-comparison", "utc": datetime.now(timezone.utc).isoformat(),
              "model": args.model or os.getenv("EXP_LLM_MODEL", "nvidia/nemotron-3.5-bolt-e4b"),
              "embedding_model": retrieval_v2.embedding_model(),
              "baseline": "V1 fast mode (current UI default); V2 includes evidence checking",
              "answers_enabled": args.answers, "dataset": str(Path(args.dataset).resolve()),
              "limitations": "Source-level retrieval metrics on fictional fixtures; not proof of real-corpus quality. "
                              "V1 covered is a nonempty-retrieval proxy. V2 coverage/verification use a model, not human labels. "
                              "Latency compares complete selected paths, not equal operations.",
              "v1": [], "v2": []}
    with isolated_indexes(corpus, work):
        ingest.build_index()
        retrieval_v2.build_index()
        for row in rows:
            for version in ("v1", "v2"):
                started = perf_counter()
                try:
                    if version == "v1":
                        result = engine.ground(row["question"], grade=False)
                        if args.answers:
                            result["answer"] = generate_answer(row["question"], result["context"], model=args.model or os.getenv("EXP_LLM_MODEL", "nvidia/nemotron-3.5-bolt-e4b"))
                    elif args.answers:
                        result = pipeline.draft(row["question"], model=args.model)
                    else:
                        result = retrieval_v2.ground(row["question"], grade_model=args.model)
                except Exception as exc:
                    result = {"error": type(exc).__name__, "kept": [], "covered": False}
                scored = score(row, result, corpus)
                scored["seconds"] = round(perf_counter() - started, 3)
                report[version].append(scored)
                print(f"{row['id']} {version}: sources={scored['retrieved_sources']} covered={scored['covered']} error={scored['error']}", flush=True)
            # Save progress so interruptions do not discard completed comparisons.
            output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["summary"] = {v: summarize(report[v]) for v in ("v1", "v2")}
    report["holdout_summary"] = {v: summarize([r for r in report[v] if r["split"] == "holdout"])
                                 for v in ("v1", "v2")}
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"Saved {output}")
    return 1 if any(r["error"] for v in ("v1", "v2") for r in report[v]) else 0
