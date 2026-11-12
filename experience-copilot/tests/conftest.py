"""Shared fixtures. Everything runs offline: chat and embeddings are faked at crag's seams, and
the real root .env is never read (it may hold a live key)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from crag.config import Settings as CragSettings
from crag.llm import LLMClient, reset_factories
from crag.nodes import web_search

from copilot.config import Settings
from copilot.ingest import build_index
from eval.fakes import install

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for name in list(os.environ):
        if name.startswith(("EXP_", "CRAG_")) or name == "NVIDIA_API_KEY":
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setitem(CragSettings.model_config, "env_file", None)
    reset_factories()
    web_search.reset_breaker()
    yield
    reset_factories()
    web_search.reset_breaker()


@pytest.fixture
def make_settings(tmp_path):
    def _make(**kw) -> Settings:
        base = {
            "corpus_dir": str(EXAMPLES / "corpus"),
            "persist_dir": str(tmp_path / "index"),
            "persona_path": str(EXAMPLES / "persona.md"),
            "style_path": str(EXAMPLES / "style_examples.md"),
            # Dense veto off by default so tests do not depend on hash-embedding cosine values.
            "dense_threshold": 0.0,
        }
        base.update(kw)
        return Settings(**base)

    return _make


@pytest.fixture
def settings(make_settings) -> Settings:
    return make_settings()


@pytest.fixture
def client_for():
    """A no-wait, no-retry LLMClient for a copilot Settings."""

    def _make(s: Settings) -> LLMClient:
        cs = s.to_crag_settings(max_retries=0, backoff_base_s=0.0, fallback_models=[])
        return LLMClient(cs, sleep=lambda _s: None)

    return _make


@pytest.fixture
def indexed(settings):
    """The example corpus indexed with fake embeddings. Tests then call `install(handler)`."""
    install(lambda model, messages, schema: "unused")
    build_index(settings)
    return settings
