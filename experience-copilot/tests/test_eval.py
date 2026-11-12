"""Eval harness plumbing (offline), judge independence, and the app's missing-key screen."""
import json
from pathlib import Path

import pytest

from eval.fakes import install, stub_handler
from eval.judge import make_judge, parse_scores
from eval.run import QUESTIONS, evaluate, load_questions, render_results

ROOT = Path(__file__).resolve().parents[1]


def test_question_set_shape():
    qs = load_questions(QUESTIONS)
    assert len(qs) == 17
    assert sum(q["in_kb"] for q in qs) == 12
    assert all({"id", "question", "in_kb", "labels", "length"} <= set(q) for q in qs)


def test_offline_evaluate_produces_all_metrics(settings):
    install(stub_handler)
    out = evaluate(settings, load_questions())
    m = out["metrics"]
    assert m["n"] == 17 and m["n_generated"] == 17
    for k in ("attribution_error_rate", "length_compliance_rate", "coverage_accuracy_fast",
              "coverage_accuracy_graded"):
        assert m[k] is not None
    assert m["grounding_mean"] is None  # no judge offline
    assert m["length_compliance_rate"] == 1.0  # the stub writes mid-band text
    fast = {r["id"]: r["covered_fast"] for r in out["rows"]}
    assert fast["q01"] and not fast["q09"]  # in-KB covered, unknown employer flagged
    json.dumps(out)  # serialisable


def test_judge_must_differ_from_generator(settings):
    with pytest.raises(ValueError):
        make_judge(settings, settings.answer_model)
    assert make_judge(settings, "some/other-model").model == "some/other-model"


def test_parse_scores():
    assert parse_scores('```json\n{"claims": 4, "supported": 3}\n```') == (4, 3)
    with pytest.raises(ValueError):
        parse_scores("nope")


def test_results_md_is_not_run_or_from_a_live_run_and_render_is_complete():
    """A number in RESULTS.md must trace to a recorded live result file."""
    text = (ROOT / "eval" / "RESULTS.md").read_text(encoding="utf-8")
    if "%" in text:
        assert "Result file: `results/live_" in text and "OFFLINE" not in text
    else:
        assert "not run" in text
    meta = {"time_utc": "t", "commit": "c", "answer_model": "a", "grader_model": "g",
            "judge_model": "j", "corpus_hash": "h", "questions_hash": "q", "file": "f.json"}
    metrics = {"n": 10, "attribution_error_rate": 0.0, "length_compliance_rate": 0.9,
               "regeneration_rate": 0.1, "coverage_accuracy_fast": 0.8,
               "coverage_accuracy_graded": 0.9, "grounding_mean": None, "n_judged": 0}
    md = render_results({"metrics": metrics, "meta": meta})
    assert "90%" in md and "n/a" in md
    rows = [{"in_kb": True, "generated": True, "judge_error": "PermanentError: 404"}] * 3
    md = render_results({"metrics": metrics, "meta": meta, "rows": rows})
    assert "not measured: the judge call failed for 3 of 3 attempts" in md


def test_app_shows_key_message_when_missing():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not at.exception
    assert any(".env" in e.value for e in at.error)
