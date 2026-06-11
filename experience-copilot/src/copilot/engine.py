"""Grounding engine — reuses crag's retriever; grades chunks IN PARALLEL (or skips them for speed).

Speed notes:
- `grade=False` (fast mode) skips per-chunk grading entirely → one fewer LLM call per chunk.
- When grading, chunks are graded concurrently with a fast model, so latency is ~one call instead
  of one-per-chunk. No web fallback here (see README); the CLI/UI handles low coverage.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from crag.nodes.grade import GRADE_PROMPT, GradeDecision
from crag.nodes.retrieve import retrieve

from .config import configure_crag, get_settings
from .llm import FAST_MODEL, chat


def _grade_one(question: str, doc, model: str) -> bool:
    """Grade one chunk. On failure or empty structured output, KEEP the chunk (safe default)."""
    try:
        grader = chat(model).with_structured_output(GradeDecision)
        result = grader.invoke(GRADE_PROMPT.format(question=question, content=doc.page_content))
        return bool(result.relevant) if result is not None else True
    except Exception:
        return True


def ground(question: str, *, grade: bool = True, grade_model: str | None = None) -> dict:
    s = configure_crag(get_settings())
    state = {"question": question, "steps": []}
    state.update(retrieve(state))
    docs = state.get("documents", [])

    if not grade:
        context = "\n\n---\n\n".join(d.page_content for d in docs)
        return {"context": context, "kept": docs, "n_relevant": len(docs),
                "covered": bool(docs), "graded": False}

    model = grade_model or FAST_MODEL
    if docs:
        with ThreadPoolExecutor(max_workers=min(8, len(docs))) as ex:
            grades = list(ex.map(lambda d: _grade_one(question, d, model), docs))
    else:
        grades = []
    kept = [d for d, g in zip(docs, grades) if g]
    context = "\n\n---\n\n".join(d.page_content for d in kept)
    return {"context": context, "kept": kept, "n_relevant": len(kept),
            "covered": len(kept) >= s.relevance_threshold, "graded": True}
