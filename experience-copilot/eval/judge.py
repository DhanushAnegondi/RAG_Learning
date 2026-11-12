"""Grounding judge: a model DIFFERENT from the generator scores how much of an answer is supported.

Why separate: a judge that shares the generator's model inflates scores (self-preference), so
`make_judge` refuses to build one with the same model id.
"""
from __future__ import annotations

import json
import re

from crag.llm import LLMClient

from copilot.config import Settings

DEFAULT_JUDGE_MODEL = "deepseek-ai/deepseek-v4.1-flash"

PROMPT = """You are a strict fact-checker. Split the ANSWER into its factual claims and decide
for each whether the CONTEXT supports it.

CONTEXT:
{context}

ANSWER: {answer}

Reply with ONLY JSON:
{{"claims": <number of claims>, "supported": <number supported by the context>}}"""


def parse_scores(text: str) -> tuple[int, int]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"no JSON in judge reply: {text[:100]!r}")
    d = json.loads(m.group(0))
    return int(d["claims"]), int(d["supported"])


class Judge:
    def __init__(self, client: LLMClient, model: str):
        self.client, self.model = client, model

    def grounding(self, answer: str, context: str) -> float | None:
        """Share of claims supported by the context; None when the answer makes no claims."""
        text = self.client.complete(
            [("user", PROMPT.format(context=context or "(no context)", answer=answer))],
            purpose="judge",
            model=self.model,
        )
        claims, supported = parse_scores(text)
        return min(supported, claims) / claims if claims > 0 else None


def make_judge(settings: Settings, judge_model: str = DEFAULT_JUDGE_MODEL) -> Judge:
    if judge_model == settings.answer_model:
        raise ValueError("judge model must differ from the answer model")
    # the judge reads a whole answer plus context and may reason first: give it room
    cs = settings.to_crag_settings(
        llm_model=judge_model, fallback_models=[], llm_timeout_s=120.0, llm_total_budget_s=300.0
    )
    return Judge(LLMClient(cs), judge_model)
