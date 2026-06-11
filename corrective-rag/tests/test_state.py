from crag.state import CRAGState


def test_state_has_the_documented_contract():
    keys = set(CRAGState.__annotations__)
    assert {"question", "documents", "grades", "web_results", "generation", "steps"} <= keys


def test_state_accepts_partial_updates():
    # total=False => a partial dict is a valid CRAGState (nodes return partials)
    state: CRAGState = {"question": "hi"}
    state.update({"grades": [True]})
    assert state["question"] == "hi" and state["grades"] == [True]
