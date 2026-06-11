"""grade node — score EACH retrieved chunk for relevance with a structured (yes/no) LLM call.

Why per-chunk (HANDOFF M2 why): a single grade for the whole set tells you the retrieval was
weak but not WHICH chunks to drop. Per-chunk grades let `generate` keep only the relevant context
and let `decide` count how many survived — the signal the correction branch needs.
"""
from __future__ import annotations

from langchain_core.documents import Document
from pydantic import BaseModel, Field

from ..llm import get_llm

GRADE_PROMPT = (
    "You are grading whether a retrieved document is relevant to a user question.\n"
    "Question: {question}\n\n"
    "Document:\n{content}\n\n"
    "Is this document relevant to answering the question? "
    "Answer strictly with the structured schema (relevant: true/false). "
    "Be strict: only 'true' if it contains information that helps answer the question."
)


class GradeDecision(BaseModel):
    """Structured grader output. with_structured_output forces the model to fill this."""

    relevant: bool = Field(description="True iff the document helps answer the question.")


def grade_documents(state: dict) -> dict:
    grader = get_llm().with_structured_output(GradeDecision)
    grades: list[bool] = []
    for doc in state.get("documents", []):
        msg = GRADE_PROMPT.format(question=state["question"], content=_text(doc))
        result = grader.invoke(msg)
        grades.append(bool(result.relevant))
    return {"grades": grades, "steps": state.get("steps", []) + ["grade"]}


def _text(doc: Document) -> str:
    return doc.page_content if isinstance(doc, Document) else str(doc)
