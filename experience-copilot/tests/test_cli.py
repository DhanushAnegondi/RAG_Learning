"""CLI exit codes and an end-to-end run on the example corpus with fakes."""
import pytest
from pydantic import SecretStr

from copilot import cli
from eval.fakes import install, stub_handler


@pytest.mark.parametrize("argv", [["ingest"], ["answer", "What did you build?"]])
def test_exit_2_without_key(argv, capsys, settings, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    assert cli.main(argv) == 2
    assert ".env" in capsys.readouterr().err


def test_placeholder_key_counts_as_missing(settings, monkeypatch, capsys):
    s = settings.model_copy(update={"nvidia_api_key": SecretStr("PASTE_YOUR_KEY_HERE")})
    monkeypatch.setattr(cli, "get_settings", lambda: s)
    assert cli.main(["ingest"]) == 2


def test_ingest_then_answer_end_to_end(settings, monkeypatch, capsys):
    s = settings.model_copy(update={"nvidia_api_key": SecretStr("test-key-not-real")})
    monkeypatch.setattr(cli, "get_settings", lambda: s)
    install(stub_handler)
    assert cli.main(["ingest"]) == 0
    assert "6 added" in capsys.readouterr().out
    code = cli.main(
        ["answer", "How did you reduce cloud costs at Contoso?", "--length", "short",
         "--tone", "formal", "--fast"]
    )
    out = capsys.readouterr().out
    assert code == 0 and "covered" in out and "Contoso" in out and "NOT covered" not in out
    code = cli.main(["answer", "What did you accomplish at Fabrikam?", "--length", "short",
                     "--tone", "formal", "--fast"])
    assert code == 0 and "NOT covered" in capsys.readouterr().out
