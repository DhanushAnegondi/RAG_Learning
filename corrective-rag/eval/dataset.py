"""Load and validate the eval set; hash the inputs so every result file records what it ran on.

Why hashes: a before/after comparison is only valid if both runs used the same corpus and the same
eval set. The hashes go into every result file so `report.py` can show them.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
PROJECT_DIR = EVAL_DIR.parent
EVAL_SET = EVAL_DIR / "eval_set.jsonl"
CORPUS_DIR = PROJECT_DIR / "data" / "corpus"

CATEGORIES = ("exact_term", "semantic", "out_of_corpus", "unanswerable")
ROUTES = ("local", "web", "abstain")
REQUIRED = ("id", "question", "ground_truth", "category", "evidence", "expected_route")
CORPUS_SUFFIXES = (".md", ".txt", ".pdf")


def load_eval_set(path: Path | str = EVAL_SET) -> list[dict]:
    """Read and validate the JSONL eval set. Raises ValueError with the row id on a bad row."""
    rows: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if line.strip():
                rows.append(validate_row(json.loads(line), n))
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate ids in eval set")
    return rows


def stratified_limit(rows: list[dict], n: int) -> list[dict]:
    """First `n` rows taken round-robin across categories (categories in eval-set order, rows in
    file order within each), so a small `--limit` still covers every category. Deterministic."""
    if n < 1:
        raise ValueError("limit must be >= 1")
    buckets: dict[str, list[dict]] = {}
    for r in rows:
        buckets.setdefault(r["category"], []).append(r)
    out: list[dict] = []
    while len(out) < min(n, len(rows)):
        for b in buckets.values():
            if b and len(out) < n:
                out.append(b.pop(0))
    return out


def validate_row(row: dict, line_no: int = 0) -> dict:
    where = f"eval row {row.get('id', f'line {line_no}')}"
    missing = [k for k in REQUIRED if k not in row]
    if missing:
        raise ValueError(f"{where}: missing fields {missing}")
    if row["category"] not in CATEGORIES:
        raise ValueError(f"{where}: bad category {row['category']!r}")
    if row["expected_route"] not in ROUTES:
        raise ValueError(f"{where}: bad expected_route {row['expected_route']!r}")
    if not isinstance(row["evidence"], list):
        raise ValueError(f"{where}: evidence must be a list")
    if row["category"] in ("exact_term", "semantic") and not row["evidence"]:
        raise ValueError(f"{where}: in-corpus row needs evidence substrings")
    return row


def file_sha256(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def corpus_hash(corpus_dir: Path | str = CORPUS_DIR) -> str:
    """sha256 over (relative path, content hash) of every corpus file, sorted by path."""
    root = Path(corpus_dir)
    h = hashlib.sha256()
    for p in sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in CORPUS_SUFFIXES
    ):
        h.update(p.relative_to(root).as_posix().encode("utf-8"))
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()
