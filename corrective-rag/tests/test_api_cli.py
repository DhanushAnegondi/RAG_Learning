"""HTTP API via TestClient and the CLI's key gate. Offline."""

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from crag import cli, llm
from crag.api import create_app
from crag.config import Settings
from crag.ingest import build_index
from crag.nodes import web_search as ws

from .fakes import HashEmbeddings
from .fakes_pipeline import PipelineChat


@pytest.fixture
def settings(tmp_path):
    corpus = tmp_path / "c"
    corpus.mkdir()
    (corpus / "fees.md").write_text(
        "# Fees\n\n## NSF\nCode FEE-NSF-02 charges 35 dollars.\n", encoding="utf-8"
    )
    return Settings(
        _env_file=None,
        corpus_dir=str(corpus),
        persist_dir=str(tmp_path / "store"),
        trace_dir=str(tmp_path / "tr"),
        max_retries=0,
        backoff_base_s=0.0,
        fallback_models=[],
    )


def test_healthz(settings):
    r = TestClient(create_app(settings)).get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_readyz_503_without_key_and_index(settings):
    r = TestClient(create_app(settings)).get("/readyz")
    assert r.status_code == 503
    reasons = " ".join(r.json()["reasons"])
    assert "index" in reasons and "NVIDIA_API_KEY" in reasons


def test_readyz_200_when_ready(settings):
    build_index(settings, embeddings=HashEmbeddings())
    ready = settings.model_copy(update={"nvidia_api_key": SecretStr("real-looking-key")})
    r = TestClient(create_app(ready)).get("/readyz")
    assert r.status_code == 200 and r.json()["status"] == "ready"


def test_readyz_placeholder_key_is_not_ready(settings):
    build_index(settings, embeddings=HashEmbeddings())
    ph = settings.model_copy(update={"nvidia_api_key": SecretStr("PASTE_YOUR_KEY")})
    assert TestClient(create_app(ph)).get("/readyz").status_code == 503


def test_ask_returns_answer_json(settings, monkeypatch):
    emb = HashEmbeddings()
    llm.set_embeddings_factory(lambda: emb)
    build_index(settings, embeddings=emb)
    monkeypatch.setattr(ws, "_ddgs_text", lambda *a: [])
    llm.set_chat_factory(
        lambda _m: PipelineChat(is_relevant=lambda t: "FEE-NSF-02" in t, answer="35 dollars [1].")
    )
    r = TestClient(create_app(settings)).post("/v1/ask", json={"question": "FEE-NSF-02 amount?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "35 dollars [1]." and body["route"] == "local"
    assert body["citations"][0]["source"] == "fees.md"
    for key in (
        "abstained",
        "degraded",
        "errors",
        "retrieved",
        "latency_ms",
        "llm_calls",
        "retries",
        "trace_id",
    ):
        assert key in body


@pytest.mark.parametrize("payload", [{"question": ""}, {"question": "   "}, {}, {"question": 5}])
def test_ask_invalid_is_422(settings, payload):
    assert TestClient(create_app(settings)).post("/v1/ask", json=payload).status_code == 422


def test_ask_too_long_is_422(settings):
    r = TestClient(create_app(settings)).post("/v1/ask", json={"question": "x" * 1001})
    assert r.status_code == 422


@pytest.mark.parametrize("argv", [["ingest"], ["ask", "hello"], ["serve"]])
def test_cli_exits_2_without_key(argv, capsys, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))
    assert cli.main(argv) == 2
    err = capsys.readouterr().err
    assert ".env" in err and "NVIDIA_API_KEY" in err


def test_cli_exits_2_with_placeholder_key(capsys, monkeypatch):
    monkeypatch.setattr(
        cli, "get_settings", lambda: Settings(_env_file=None, nvidia_api_key="PASTE_HERE")
    )
    assert cli.main(["ask", "hello"]) == 2


def test_cli_ask_json_with_fakes(settings, capsys, monkeypatch):
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: settings.model_copy(update={"nvidia_api_key": SecretStr("real-looking-key")}),
    )
    monkeypatch.setattr("crag.pipeline.get_settings", lambda: settings)
    monkeypatch.setattr(ws, "_ddgs_text", lambda *a: [])
    emb = HashEmbeddings()
    llm.set_embeddings_factory(lambda: emb)
    build_index(settings, embeddings=emb)
    llm.set_chat_factory(lambda _m: PipelineChat(answer="35 [1]."))
    assert cli.main(["ask", "FEE-NSF-02?", "--json"]) == 0
    assert '"trace_id"' in capsys.readouterr().out
