"""decide() / verdict_for(): the CRAG three-way table, driven by settings thresholds."""

import pytest

from crag.config import Settings
from crag.graph import decide
from crag.nodes.grade import verdict_for


@pytest.mark.parametrize(
    "grades,expected",
    [
        ([], "incorrect"),
        ([False, False, False], "incorrect"),
        ([True, False], "ambiguous"),
        ([False, True, False, False], "ambiguous"),
        ([True, True], "correct"),
        ([True, True, True, False], "correct"),
    ],
)
def test_verdict_default_thresholds(grades, expected):
    assert verdict_for(grades, 2, 1) == expected


def test_verdict_respects_thresholds():
    grades = [True, True]
    assert verdict_for(grades, 3, 2) == "ambiguous"
    assert verdict_for(grades, 3, 3) == "incorrect"
    assert verdict_for([True], 3, 2) == "incorrect"


@pytest.mark.parametrize(
    "grades,web,expected",
    [
        ([True, True], True, "generate"),
        ([True, False], True, "rewrite_query"),
        ([False, False], True, "rewrite_query"),
        ([True, False], False, "generate"),  # web off: answer locally
        ([False, False], False, "generate"),  # web off: generate abstains
    ],
)
def test_decide_routes(grades, web, expected):
    s = Settings(_env_file=None, web_enabled=web)
    assert decide({"grades": grades}, s) == expected


def test_decide_uses_settings_thresholds_and_is_pure():
    s = Settings(_env_file=None, correct_threshold=3, ambiguous_threshold=2)
    state = {"grades": [True, True], "question": "q"}
    assert decide(state, s) == "rewrite_query"
    assert state == {"grades": [True, True], "question": "q"}
    s2 = Settings(_env_file=None, correct_threshold=3, ambiguous_threshold=2)
    assert decide({"grades": [True, True, True]}, s2) == "generate"
