"""Per-chunk grader: one structured yes/no per document, parallel to `documents`."""
from crag.nodes.grade import GradeDecision, grade_documents


def test_grade_is_per_chunk(patch_llm, fake_llm, doc):
    patch_llm(fake_llm(decisions=[True, False]))
    state = {"question": "q", "documents": [doc("a"), doc("b")]}
    out = grade_documents(state)
    assert out["grades"] == [True, False]
    assert "grade" in out["steps"]


def test_grade_handles_empty_documents(patch_llm, fake_llm):
    patch_llm(fake_llm(decisions=[True]))
    out = grade_documents({"question": "q", "documents": []})
    assert out["grades"] == []


def test_grade_decision_schema():
    # structured-output target: a single boolean field
    assert set(GradeDecision.model_fields) == {"relevant"}
    assert GradeDecision(relevant=True).relevant is True
