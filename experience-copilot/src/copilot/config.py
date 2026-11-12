"""Copilot settings: pydantic-settings, `EXP_` prefix, read from the repo-root `.env`.

Why only the root `.env`: crag's default chat factory reads the API key through crag's own
settings (same root `.env` / process env), so a key placed anywhere else would pass the copilot's
check and then fail inside crag. One file, one source of truth.

No env mutation: the copilot never writes `os.environ`. `to_crag_settings()` builds an explicit
crag `Settings` object from these values instead.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]  # the experience-copilot project root
REPO_ROOT = ROOT.parent
ROOT_ENV = REPO_ROOT / ".env"
PLACEHOLDER_PREFIX = "PASTE_"

# Allowed control values (UI dropdowns + CLI flags). "auto" => let the suggester decide.
LENGTHS = ("auto", "short", "medium", "long")
TONES = ("auto", "formal", "professional", "conversational", "humanized")

# Answer models offered in the UI (all responded on NVIDIA NIM when probed; see
# scripts/probe_models.py). The first is the default.
MODELS: dict[str, str] = {
    "Quality: Nemotron Nano 30B (default)": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "Balanced: Nemotron 3.5 Lightning 30B": "nvidia/nemotron-3.5-lightning-30b-a3b",
    "Fast: Nemotron 3.5 Bolt": "nvidia/nemotron-3.5-bolt-e4b",
}


class Settings(BaseSettings):
    """All copilot knobs. Env prefix `EXP_`; the API key is read as plain `NVIDIA_API_KEY`."""

    model_config = SettingsConfigDict(
        env_prefix="EXP_",
        env_file=str(ROOT_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    nvidia_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("NVIDIA_API_KEY", "EXP_NVIDIA_API_KEY")
    )

    # Paths: relative values resolve against the project root.
    corpus_dir: str = "data/corpus"
    persist_dir: str = "chroma_store"
    persona_path: str = "profile/persona.md"
    style_path: str = "profile/style_examples.md"

    answer_model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
    grader_model: str = "nvidia/nemotron-3.5-bolt-e4b"
    fallback_models: Annotated[list[str], NoDecode] = [
        "nvidia/nemotron-3.5-lightning-30b-a3b",
        "nvidia/nemotron-3.5-bolt-e4b",
    ]

    top_k: int = Field(5, ge=1, le=50)
    fetch_k: int = Field(12, ge=1, le=200)

    # Coverage (see engine.assess_coverage). `coverage_threshold` is the graded rule: at least this
    # many chunks judged relevant. The other two drive the fast (ungraded) rule.
    coverage_threshold: int = Field(1, ge=1, le=50)
    lexical_min_hits: int = Field(2, ge=1, le=10)
    # Cosine floor a lexically matching chunk must also reach (dense alone never marks covered;
    # see engine docstring). Calibrated 2026-11-11 on the example corpus with nemotron-3.5-embed-1b:
    # in-KB best cosine 0.23-0.58, out-of-KB 0.11-0.34 (those are rejected by the entity and lexical
    # rules). At 0.3 the veto wrongly rejected two in-KB questions and caught none.
    dense_threshold: float = Field(0.2, ge=0.0, le=1.0)

    # Employer names that are also common words (e.g. "Target"): exempt from the attribution guard.
    attribution_ignore: Annotated[list[str], NoDecode] = []

    @field_validator("fallback_models", "attribution_ignore", mode="before")
    @classmethod
    def _split_models(cls, v):
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                return json.loads(s)
            return [m.strip() for m in s.split(",") if m.strip()]
        return v

    @field_validator("corpus_dir", "persist_dir", "persona_path", "style_path")
    @classmethod
    def _absolute(cls, v: str) -> str:
        p = Path(v)
        return str(p if p.is_absolute() else (ROOT / p).resolve())

    @property
    def key_configured(self) -> bool:
        """True only for a real-looking key; the `PASTE_...` placeholder counts as missing."""
        if self.nvidia_api_key is None:
            return False
        v = self.nvidia_api_key.get_secret_value().strip()
        return bool(v) and not v.startswith(PLACEHOLDER_PREFIX)

    def to_crag_settings(self, **overrides):
        """An explicit crag `Settings` built from these values (no environment involved).

        Thresholds: crag's `correct_threshold` carries our graded coverage threshold. Overrides
        let tests/eval tune retries, timeouts or models."""
        from crag.config import Settings as CragSettings

        kw: dict = {
            "llm_model": self.answer_model,
            "grader_model": self.grader_model,
            "fallback_models": list(self.fallback_models),
            "corpus_dir": self.corpus_dir,
            "persist_dir": self.persist_dir,
            "top_k": self.top_k,
            "fetch_k": max(self.fetch_k, self.top_k),
            "correct_threshold": self.coverage_threshold,
            "ambiguous_threshold": 1,
            "web_enabled": True,  # web is opt-in per call in the copilot, never automatic
        }
        if self.nvidia_api_key is not None:
            kw["nvidia_api_key"] = self.nvidia_api_key
        kw.update(overrides)
        return CragSettings(**kw)


def get_settings() -> Settings:
    """A fresh Settings each call: cheap, and lets tests change env between calls."""
    return Settings()
