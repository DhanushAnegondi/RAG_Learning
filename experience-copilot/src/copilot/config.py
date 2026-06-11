"""Settings + wiring the reused `crag` engine at THIS project's corpus/index."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]  # the experience-copilot project root

# Allowed control values (UI dropdowns + CLI flags). "auto" => let the suggester decide.
LENGTHS = ("auto", "short", "medium", "long")
TONES = ("auto", "formal", "professional", "conversational", "humanized")


def _abspath(p: str) -> str:
    return p if os.path.isabs(p) else str((ROOT / p).resolve())


@dataclass(frozen=True)
class Settings:
    nvidia_api_key: str | None
    corpus_dir: str
    persist_dir: str
    relevance_threshold: int
    persona_path: str
    style_path: str


def get_settings() -> Settings:
    return Settings(
        nvidia_api_key=os.getenv("NVIDIA_API_KEY"),
        corpus_dir=_abspath(os.getenv("EXP_CORPUS_DIR", "data/corpus")),
        persist_dir=_abspath(os.getenv("EXP_PERSIST_DIR", "chroma_store")),
        relevance_threshold=int(os.getenv("EXP_RELEVANCE_THRESHOLD", "1")),
        persona_path=_abspath(os.getenv("EXP_PERSONA", "profile/persona.md")),
        style_path=_abspath(os.getenv("EXP_STYLE", "profile/style_examples.md")),
    )


def configure_crag(s: Settings | None = None) -> Settings:
    """Point the reused crag engine at this project's corpus/index/threshold. Call before any
    crag retrieve/ingest so crag.get_settings() picks up these paths."""
    s = s or get_settings()
    os.environ["CRAG_CORPUS_DIR"] = s.corpus_dir
    os.environ["CRAG_PERSIST_DIR"] = s.persist_dir
    os.environ["CRAG_RELEVANCE_THRESHOLD"] = str(s.relevance_threshold)
    return s
