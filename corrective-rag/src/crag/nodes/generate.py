"""generate node — answer from the surviving context (relevant chunks + any web results)."""
from __future__ import annotations

from langchain_core.documents import Document

from ..llm import get_llm

GENERATE_PROMPT = (
    "Answer the question using ONLY the context below. If the context does not contain the "
    "answer, say you don't know — do not invent facts.\n\n"
    "Question: {question}\n\n"
    "Context:\n{context}\n\n"
    "Answer:"
)


def generate(state: dict) -> dict:
    context = _format_context(state)
    prompt = GENERATE_PROMPT.format(question=state["question"], context=context)
    resp = get_llm().invoke(prompt)
    text = getattr(resp, "content", resp)
    return {"generation": text, "steps": state.get("steps", []) + ["generate"]}


def _format_context(state: dict) -> str:
    """Use only chunks graded relevant (if grades exist), plus any web results."""
    docs = state.get("documents", [])
    grades = state.get("grades")
    if grades:
        kept = [d for d, g in zip(docs, grades) if g]
    else:
        kept = list(docs)
    kept = kept + state.get("web_results", [])
    return "\n\n---\n\n".join(_text(d) for d in kept) if kept else "(no context)"


def _text(doc: Document) -> str:
    return doc.page_content if isinstance(doc, Document) else str(doc)
