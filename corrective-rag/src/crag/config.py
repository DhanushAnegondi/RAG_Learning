"""Settings: validated, typed configuration read from the environment and `.env` files.

Why pydantic-settings: a bad value (top_k > fetch_k, a threshold out of order) should fail at
startup with a clear message, not surface as odd retrieval behaviour later. The API key is a
SecretStr so it cannot leak through repr/logging by accident; the only way to read it is an
explicit `.get_secret_value()` at the provider boundary (llm.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_DIR.parent
# Later files override earlier ones: the repo-root .env is shared by both projects, a project-level
# .env wins for local overrides.
ENV_FILES = (str(REPO_ROOT / ".env"), str(PROJECT_DIR / ".env"))

PLACEHOLDER_PREFIX = "PASTE_"


class Settings(BaseSettings):
    """All runtime knobs. Env prefix `CRAG_`; the API key is also read as plain `NVIDIA_API_KEY`."""

    model_config = SettingsConfigDict(
        env_prefix="CRAG_",
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    nvidia_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("NVIDIA_API_KEY", "CRAG_NVIDIA_API_KEY")
    )

    # Defaults verified live on build.nvidia.com on 2026-11-11. The Llama 3.x and nv-embedqa-e5-v5
    # endpoints this project started on were retired (HTTP 410) during 2026.
    llm_model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
    grader_model: str = "nvidia/nemotron-3.5-bolt-e4b"
    fallback_models: Annotated[list[str], NoDecode] = [
        "nvidia/nemotron-3.5-lightning-30b-a3b",
        "nvidia/nemotron-3.5-bolt-e4b",
    ]
    embed_model: str = "nvidia/nemotron-3.5-embed-1b"

    retrieval_mode: Literal["hybrid", "dense", "bm25"] = "hybrid"
    top_k: int = Field(4, ge=1, le=50)
    fetch_k: int = Field(12, ge=1, le=200)
    rrf_k: int = Field(60, ge=1)

    correct_threshold: int = Field(2, ge=1, le=50)
    ambiguous_threshold: int = Field(1, ge=1, le=50)

    # Output cap per chat call, reasoning tokens included (the SDK default of 1024 left reasoning
    # models with empty answers in the 2026-11-11 live eval).
    llm_max_tokens: int = Field(4096, ge=64, le=32768)
    llm_timeout_s: float = Field(30.0, gt=0)
    llm_total_budget_s: float = Field(90.0, gt=0)
    max_retries: int = Field(3, ge=0, le=10)
    backoff_base_s: float = Field(0.5, ge=0)

    web_enabled: bool = True
    web_max_results: int = Field(4, ge=1, le=20)
    web_timeout_s: float = Field(10.0, gt=0)

    max_question_chars: int = Field(1000, ge=1)

    persist_dir: str = str(PROJECT_DIR / "chroma_store")
    corpus_dir: str = str(PROJECT_DIR / "data" / "corpus")
    trace_dir: str = str(PROJECT_DIR / "traces")

    @field_validator("fallback_models", mode="before")
    @classmethod
    def _split_models(cls, v):
        """Accept a JSON list, a comma-separated string, or a real list."""
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                import json

                return json.loads(s)
            return [m.strip() for m in s.split(",") if m.strip()]
        return v

    @model_validator(mode="after")
    def _check_ordering(self) -> Settings:
        if self.top_k > self.fetch_k:
            raise ValueError(f"top_k ({self.top_k}) must be <= fetch_k ({self.fetch_k})")
        if self.ambiguous_threshold > self.correct_threshold:
            raise ValueError(
                f"ambiguous_threshold ({self.ambiguous_threshold}) must be <= "
                f"correct_threshold ({self.correct_threshold})"
            )
        return self

    @property
    def key_configured(self) -> bool:
        """True only for a real-looking key. The shipped `.env` holds a `PASTE_...` placeholder,
        which must behave exactly like 'no key' (clear exit-2 message, not a 401 from the API)."""
        if self.nvidia_api_key is None:
            return False
        v = self.nvidia_api_key.get_secret_value().strip()
        return bool(v) and not v.startswith(PLACEHOLDER_PREFIX)

    @property
    def relevance_threshold(self) -> int:
        """v0 name kept so the old graph keeps importing until it is rewritten."""
        return self.correct_threshold


def get_settings() -> Settings:
    """A fresh Settings each call: cheap, and lets tests monkeypatch env between calls."""
    return Settings()
