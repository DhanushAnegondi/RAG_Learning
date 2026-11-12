"""grade_web node: grade web results with the same grader as local chunks."""

from __future__ import annotations

from ..config import Settings
from ..llm import LLMClient
from ..state import CRAGState
from .grade import grade_texts


def grade_web(state: CRAGState, client: LLMClient, settings: Settings) -> dict:
    web = state.get("web_chunks", [])
    grades = grade_texts(state["question"], [d.page_content for d in web], client, settings)
    return {"web_grades": grades, "steps": [*state.get("steps", []), "grade_web"]}
