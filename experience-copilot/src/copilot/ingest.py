"""Ingest: crag's incremental indexer plus an enricher that stamps each chunk with its experience.

Why: every retrieved chunk must carry WHO it belongs to, or the model blends one employer's work
into another's story. The label is the top-level corpus folder (`interview/<Employer>/...` maps to
the employer). It is stored in metadata (`experience`) and prefixed onto the text as
`[Experience: X]` so both the embedder, BM25 and the generator see it.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from crag.ingest import BM25_FILE, IndexReport
from crag.ingest import build_index as crag_build_index
from crag.ingest.loader import SUPPORTED
from langchain_core.documents import Document

from .config import Settings, get_settings

PREFIX_RE = re.compile(r"^\[Experience: [^\]\n]*\]\n")


def experience_label(source: str) -> str:
    """Label for a corpus-relative source path (forward or back slashes).

    `Rocket/a.md` and `interview/Rocket/stories/b.md` both give `Rocket`. A file directly in the
    corpus root has no folder, so its stem is the label."""
    parts = [p for p in source.replace("\\", "/").split("/") if p]
    if not parts:
        return "General"
    if parts[0] == "interview" and len(parts) > 1:
        return parts[1] if len(parts) > 2 else Path(parts[1]).stem
    if len(parts) == 1:
        return Path(parts[0]).stem
    return parts[0]


def strip_label(text: str) -> str:
    """Remove the `[Experience: X]` prefix (for lexical matching on the body only)."""
    return PREFIX_RE.sub("", text, count=1)


def enrich(chunk: Document) -> Document:
    """Crag enricher: add `experience` metadata and the `[Experience: X]` text prefix."""
    label = experience_label(str(chunk.metadata.get("source", "")))
    chunk.metadata["experience"] = label
    if not PREFIX_RE.match(chunk.page_content):  # idempotent
        chunk.page_content = f"[Experience: {label}]\n{chunk.page_content}"
    return chunk


def is_ingestable(rel_path: str) -> bool:
    """False for README*, dotfiles (.gitkeep, .DS_Store) and anything under a dot-directory.

    A README describes the corpus, it is not experience; indexing it would create a bogus label."""
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
    if any(p.startswith(".") for p in parts):
        return False
    return bool(parts) and not parts[-1].lower().startswith("readme")


def stage_corpus(s: Settings) -> Path:
    """Mirror the ingestable corpus files into `<persist_dir>/_staged_corpus`.

    crag's indexer reads every file under `corpus_dir` and has no filter hook, so the copilot
    hands it a filtered copy. Paths relative to the staged root equal those of the real corpus, so
    chunk ids and labels are unchanged."""
    src = Path(s.corpus_dir)
    dest = Path(s.persist_dir) / "_staged_corpus"
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        for p in sorted(src.rglob("*")):
            rel = p.relative_to(src).as_posix()
            if p.is_file() and p.suffix.lower() in SUPPORTED and is_ingestable(rel):
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dest / rel)
    return dest


def build_index(settings: Settings | None = None, rebuild: bool = False) -> IndexReport:
    """Bring the index in sync with the corpus (incremental). Returns crag's `IndexReport`.

    Pass `rebuild=True` after changing the enricher or label rule: file hashes do not change.
    Raises ValueError when the corpus has no ingestable documents."""
    s = settings or get_settings()
    staged = stage_corpus(s)
    return crag_build_index(
        s.to_crag_settings(corpus_dir=str(staged)), rebuild=rebuild, enricher=enrich
    )


def known_labels(settings: Settings | None = None, *, include_root_files: bool = False) -> set[str]:
    """Every experience label that exists: from the index (if built) and from the corpus tree.

    The attribution guard needs ALL labels, not just the retrieved ones, to spot a name that
    leaked in from a chunk that was not used. Labels of files directly in the corpus root
    (`resume.md` -> "resume") are not employers and are left out unless `include_root_files`."""
    s = settings or get_settings()
    labels: set[str] = set()
    bm25 = Path(s.persist_dir) / BM25_FILE
    if bm25.exists():
        try:
            for rec in json.loads(bm25.read_text(encoding="utf-8")):
                meta = rec.get("metadata") or {}
                lab = meta.get("experience")
                root_file = "/" not in str(meta.get("source", "")).replace("\\", "/")
                if lab and (include_root_files or not root_file):
                    labels.add(str(lab))
        except (OSError, ValueError):
            pass
    root = Path(s.corpus_dir)
    if root.is_dir():
        for p in root.rglob("*"):
            rel = p.relative_to(root).as_posix()
            if p.is_file() and p.suffix.lower() in SUPPORTED and is_ingestable(rel):
                if include_root_files or "/" in rel:
                    labels.add(experience_label(rel))
    return labels
