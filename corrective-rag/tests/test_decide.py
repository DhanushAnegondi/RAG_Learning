"""decide() is the interview-critical routing function. It must be pure and key-free."""
from crag.graph import decide


def test_enough_relevant_routes_to_generate():
    # default threshold is 2
    assert decide({"grades": [True, True, False]}) == "generate"


def test_too_few_relevant_routes_to_correction():
    assert decide({"grades": [True, False, False]}) == "transform_query"


def test_no_grades_routes_to_correction():
    assert decide({"grades": []}) == "transform_query"
    assert decide({}) == "transform_query"


def test_all_relevant_routes_to_generate():
    assert decide({"grades": [True, True, True]}) == "generate"


def test_threshold_is_configurable(monkeypatch):
    monkeypatch.setenv("CRAG_RELEVANCE_THRESHOLD", "1")
    assert decide({"grades": [True, False, False]}) == "generate"


def test_decide_does_not_mutate_state():
    state = {"grades": [False, False]}
    before = dict(state)
    decide(state)
    assert state == before
