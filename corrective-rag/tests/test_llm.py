"""LLMClient: retry, fallback, permanent fail-fast, structured parse fallback. No real sleeping."""

import time

import pytest
from pydantic import BaseModel

from crag import llm
from crag.config import Settings
from crag.errors import ParseError, PermanentError, TransientError
from crag.observability import run_context

from .fakes import ScriptedChat

MAIN, FB1, FB2 = "m/main", "m/fb1", "m/fb2"
NAMES = {"main": MAIN, "fb1": FB1, "fb2": FB2}


class Grade(BaseModel):
    relevant: bool


@pytest.fixture
def setup():
    settings = Settings(
        _env_file=None,
        llm_model=MAIN,
        fallback_models=[FB1, FB2],
        max_retries=2,
        backoff_base_s=0.1,
    )
    sleeps: list[float] = []
    chats: dict[str, ScriptedChat] = {}

    def install(**scripts):
        for key, spec in scripts.items():
            chats[NAMES[key]] = ScriptedChat(NAMES[key], **spec)
        llm.set_chat_factory(lambda m: chats[m])

    client = llm.LLMClient(settings, sleep=sleeps.append)
    return client, install, chats, sleeps


def test_retry_then_succeed(setup):
    client, install, chats, sleeps = setup
    install(main={"script": [Exception("[429] Too Many Requests"), Exception("[503] x"), "ok"]})
    with run_context() as ctx:
        assert client.complete([("user", "hi")], purpose="gen") == "ok"
    assert chats[MAIN].calls == 3
    assert len(sleeps) == 2 and all(s >= 0 for s in sleeps)
    assert ctx.retries == 2 and ctx.fallbacks == 0
    assert ctx.llm_calls[0].model == MAIN and ctx.llm_calls[0].error is None


def test_retries_exhausted_uses_fallback_model(setup):
    client, install, chats, _ = setup
    install(main={"script": [Exception("[500] boom")]}, fb1={"script": ["from fallback"]})
    with run_context() as ctx:
        assert client.complete([("user", "q")], purpose="gen") == "from fallback"
    assert chats[MAIN].calls == 3  # 1 try + max_retries=2
    assert chats[FB1].calls == 1
    assert ctx.fallbacks == 1
    assert ctx.llm_calls[0].model == FB1 and ctx.llm_calls[0].fallback_used


def test_all_models_fail_raises_transient_and_records(setup):
    client, install, _, _ = setup
    err = {"script": [Exception("[500] boom")]}
    install(main=err, fb1=err, fb2=err)
    with run_context() as ctx, pytest.raises(TransientError):
        client.complete([("user", "q")], purpose="gen")
    assert ctx.errors and "gen" in ctx.errors[0]


def test_permanent_error_not_retried_and_raised(setup):
    client, install, chats, sleeps = setup
    install(main={"script": [Exception("[401] Unauthorized")]}, fb1={"script": ["nope"]})
    with pytest.raises(PermanentError):
        client.complete([("user", "q")], purpose="gen")
    assert chats[MAIN].calls == 1 and sleeps == [] and chats[FB1].calls == 0


def test_model_not_found_tries_next_model(setup):
    client, install, chats, sleeps = setup
    install(main={"script": [Exception("[404] Not Found")]}, fb1={"script": ["alt"]})
    assert client.complete([("user", "q")], purpose="gen") == "alt"
    assert chats[MAIN].calls == 1 and sleeps == []


def test_explicit_model_overrides_primary(setup):
    client, install, _, _ = setup
    install(fb2={"script": ["grader says hi"]})
    assert client.complete([("user", "q")], purpose="grade", model=FB2) == "grader says hi"


def test_timeout_is_transient():
    settings = Settings(_env_file=None, llm_timeout_s=0.05, max_retries=0, fallback_models=[])

    class Slow:
        def invoke(self, _m):
            time.sleep(0.5)

    llm.set_chat_factory(lambda m: Slow())
    with pytest.raises(TransientError):
        llm.LLMClient(settings, sleep=lambda s: None).complete([("user", "q")], purpose="gen")


def test_structured_native_success(setup):
    client, install, _, _ = setup
    install(main={"script": ["x"], "structured_script": [Grade(relevant=True)]})
    assert client.structured([("user", "q")], Grade, purpose="grade").relevant is True


def test_structured_none_falls_back_to_plain_text_json(setup):
    client, install, chats, _ = setup
    fenced = 'Sure!\n```json\n{"relevant": false}\n```'
    install(main={"script": [fenced], "structured_script": [None]})
    out = client.structured([("user", "q")], Grade, purpose="grade")
    assert out.relevant is False
    assert chats[MAIN].structured_calls == 1 and chats[MAIN].calls == 1
    assert "JSON" in chats[MAIN].last_messages[-1][1]


def test_structured_unparseable_twice_raises_parse_error(setup):
    client, install, chats, _ = setup
    install(main={"script": ["no json here"], "structured_script": [None]})
    with run_context() as ctx, pytest.raises(ParseError):
        client.structured([("user", "q")], Grade, purpose="grade")
    assert chats[MAIN].calls == 1  # exactly one plain-text retry, no model hopping
    assert ctx.errors


def test_default_factory_without_key_is_permanent_error():
    client = llm.LLMClient(Settings(_env_file=None), sleep=lambda s: None)
    with pytest.raises(PermanentError):
        client.complete([("user", "q")], purpose="gen")


def test_structured_build_failure_falls_back_to_plain_text(setup):
    client, install, chats, _ = setup
    install(main={"script": ['{"relevant": true}']})

    def boom(_schema):
        raise NotImplementedError("no native structured output")

    chats[MAIN].with_structured_output = boom
    assert client.structured([("user", "q")], Grade, purpose="grade").relevant is True
    assert chats[MAIN].calls == 1


def test_total_budget_stops_retries_and_fallback():
    settings = Settings(
        _env_file=None,
        llm_model=MAIN,
        fallback_models=[FB1],
        max_retries=5,
        llm_total_budget_s=0.05,
    )
    chats = {
        MAIN: ScriptedChat(MAIN, [Exception("[500] boom")]),
        FB1: ScriptedChat(FB1, ["fallback"]),
    }
    llm.set_chat_factory(lambda m: chats[m])
    client = llm.LLMClient(settings, sleep=lambda s: time.sleep(0.1))
    with pytest.raises(TransientError):
        client.complete([("user", "q")], purpose="gen")
    assert chats[MAIN].calls == 1 and chats[FB1].calls == 0


def test_default_chat_uses_client_settings_max_tokens(monkeypatch):
    """Reasoning models spend max_tokens on thinking; the cap comes from the client settings."""
    import sys
    import types

    from crag import llm as llm_mod
    from crag.config import Settings

    seen = {}

    class FakeChat:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setitem(
        sys.modules, "langchain_nvidia_ai_endpoints", types.SimpleNamespace(ChatNVIDIA=FakeChat)
    )
    s = Settings(_env_file=None, nvidia_api_key="nvapi-test", llm_max_tokens=2048)
    llm_mod.LLMClient(s)._chat("m/x")
    assert seen["max_tokens"] == 2048 and seen["model"] == "m/x"
