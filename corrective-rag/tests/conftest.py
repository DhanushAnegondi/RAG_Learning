"""Shared fixtures. The whole suite runs WITHOUT a live NVIDIA_API_KEY: chat, embeddings and web
search are faked at their seams (`llm.set_chat_factory`, `set_embeddings_factory`,
`nodes.web_search._ddgs_text`)."""

from __future__ import annotations

import os
import sys

import pytest

# Make `import crag` work even if pytest's pythonpath ini isn't picked up.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))


@pytest.fixture(autouse=True)
def _isolate_provider(monkeypatch):
    """Every test: no key in the environment, no leaked factories, a closed web breaker."""
    from crag import llm, pipeline
    from crag.nodes import web_search

    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("CRAG_NVIDIA_API_KEY", raising=False)
    llm.reset_factories()
    web_search.reset_breaker()
    pipeline.reset_engines()
    yield
    llm.reset_factories()
    web_search.reset_breaker()
    pipeline.reset_engines()


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch):
    """Settings must never read the real root .env in tests (it may hold a live key)."""
    from crag.config import Settings

    monkeypatch.setitem(Settings.model_config, "env_file", None)
