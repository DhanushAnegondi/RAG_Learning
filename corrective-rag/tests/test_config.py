"""Settings validation and the placeholder-key rule."""

import pytest
from pydantic import ValidationError

from crag.config import Settings


def make(**kw):
    return Settings(_env_file=None, **kw)


def test_defaults_valid():
    s = make()
    assert s.top_k == 4 and s.fetch_k == 12 and s.retrieval_mode == "hybrid"
    assert s.fallback_models[0] == "nvidia/nemotron-3.5-lightning-30b-a3b"


@pytest.mark.parametrize(
    "kw",
    [
        {"top_k": 20, "fetch_k": 10},
        {"correct_threshold": 1, "ambiguous_threshold": 2},
        {"top_k": 0},
        {"max_retries": -1},
        {"llm_timeout_s": 0},
        {"retrieval_mode": "semantic"},
    ],
)
def test_invalid_values_rejected(kw):
    with pytest.raises(ValidationError):
        make(**kw)


def test_env_prefix_and_unprefixed_key(monkeypatch):
    monkeypatch.setenv("CRAG_TOP_K", "6")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-real-looking")
    monkeypatch.setenv("CRAG_FALLBACK_MODELS", "a/b, c/d")
    s = make()
    assert s.top_k == 6
    assert s.fallback_models == ["a/b", "c/d"]
    assert s.key_configured


def test_placeholder_key_is_not_configured(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "PASTE_YOUR_NVIDIA_KEY_HERE")
    assert not make().key_configured


def test_missing_key_not_configured():
    assert not make().key_configured


def test_key_never_in_repr(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-supersecret")
    assert "supersecret" not in repr(make())


def test_dotenv_file_read(tmp_path):
    env = tmp_path / ".env"
    env.write_text("NVIDIA_API_KEY=nvapi-from-file\nCRAG_TOP_K=3\n", encoding="utf-8")
    s = Settings(_env_file=str(env))
    assert s.top_k == 3 and s.key_configured
