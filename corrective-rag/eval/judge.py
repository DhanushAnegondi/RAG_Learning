# ruff: noqa: E501  (prose and prompt text)
"""LLM judge (independent of crag) plus deterministic key-fact match.

Why a separate module and model: the judge must not share a model, prompt, or client with the
generator, or self-preference inflates scores. It talks to ChatNVIDIA directly at temperature 0 and
returns JSON against a written rubric. `key_fact_match` is the deterministic cross-check that needs
no LLM.
"""

from __future__ import annotations

import json
import re
from typing import Any

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

DEFAULT_JUDGE_MODEL = "deepseek-ai/deepseek-v4.1-flash"  # different family from the Nemotron generator

CORRECTNESS_PROMPT = """You are a strict grader. Compare the ANSWER to the GROUND TRUTH for the QUESTION.
Score 1 if the answer states the same key facts (numbers, identifiers, conditions) as the ground
truth and does not contradict it. Score 0 if it is wrong, missing key facts, or says it does not know.
Extra correct detail is fine.

QUESTION: {question}
GROUND TRUTH: {ground_truth}
ANSWER: {answer}

Reply with ONLY JSON: {{"score": 0 or 1, "reason": "<one sentence>"}}"""

FAITHFULNESS_PROMPT = """You are a strict fact-checker. Split the ANSWER into its factual claims and
decide for each whether the CONTEXT supports it. Ignore citation markers like [1].

CONTEXT:
{context}

ANSWER: {answer}

Reply with ONLY JSON: {{"claims": <number of claims>, "supported": <number supported by the context>,
"reason": "<one sentence>"}}"""

WEB_ANSWER_PROMPT = """You grade answers to questions that the lender's own documents do not cover, so a
good system answers from a web source. Score 1 only if the ANSWER gives a specific, on-topic fact
(for example a number, name, or date) attributed to a web source, does NOT decline or say it does not
know, and does NOT fabricate anything about the fictional lender. Otherwise score 0. You cannot check
the live value; judge specificity, relevance, attribution and non-fabrication.

QUESTION: {question}
ANSWER: {answer}

Reply with ONLY JSON: {{"score": 0 or 1, "reason": "<one sentence>"}}"""

ABSTAIN_PROMPT = """Does the ANSWER decline to answer or say it does not know / the sources do not
contain the information (instead of stating a substantive answer)?

QUESTION: {question}
ANSWER: {answer}

Reply with ONLY JSON: {{"abstains": true or false}}"""

STRICT_SUFFIX = (
    "\n\nYour last reply was not valid JSON. "
    "Reply with ONLY one JSON object: no prose, no code fences."
)

_JSON = re.compile(r"\{.*\}", re.S)


def parse_json(text: str) -> dict:
    """Pull the first JSON object out of a reply (tolerates code fences and chatter)."""
    m = _JSON.search(text)
    if not m:
        raise ValueError(f"no JSON in judge reply: {text[:120]!r}")
    return json.loads(m.group(0))


def _transient(exc: BaseException) -> bool:
    s = str(exc)
    return isinstance(exc, (TimeoutError, ConnectionError)) or any(
        c in s for c in ("[429]", "[500]", "[502]", "[503]", "[504]", "timed out", "Too Many")
    )


class Judge:
    """`chat` is injectable so tests can fake the model; by default a real ChatNVIDIA."""

    def __init__(
        self, model: str = DEFAULT_JUDGE_MODEL, chat: Any = None, *, max_attempts: int = 4
    ):
        self.model = model
        self._chat = chat
        self._attempts = max_attempts
        self.parse_retries = 0

    def _model(self) -> Any:
        if self._chat is None:
            from langchain_nvidia_ai_endpoints import ChatNVIDIA

            # max_tokens includes reasoning; the SDK default (1024) returned empty judge replies
            self._chat = ChatNVIDIA(model=self.model, temperature=0, max_tokens=4096)
        return self._chat

    def _call(self, prompt: str) -> str:
        """One judge call under the shared retry policy (transient 429/5xx/timeouts only)."""

        @retry(
            retry=retry_if_exception(_transient),
            stop=stop_after_attempt(self._attempts),
            wait=wait_exponential(multiplier=1, max=20),
            reraise=True,
        )
        def call() -> str:
            resp = self._model().invoke(prompt)
            return str(getattr(resp, "content", resp))

        return call()

    def _ask(self, prompt: str) -> dict:
        try:
            return parse_json(self._call(prompt))
        except ValueError:  # includes JSONDecodeError: retry once with a stricter prompt
            self.parse_retries += 1
            return parse_json(self._call(prompt + STRICT_SUFFIX))

    def abstains(self, question: str, answer: str) -> bool:
        out = self._ask(ABSTAIN_PROMPT.format(question=question, answer=answer))
        return bool(out.get("abstains", False))

    def web_answer(self, question: str, answer: str) -> dict:
        out = self._ask(WEB_ANSWER_PROMPT.format(question=question, answer=answer))
        return {
            "score": 1 if int(out.get("score", 0)) == 1 else 0,
            "reason": str(out.get("reason", "")),
        }

    def correctness(self, question: str, ground_truth: str, answer: str) -> dict:
        out = self._ask(
            CORRECTNESS_PROMPT.format(question=question, ground_truth=ground_truth, answer=answer)
        )
        return {
            "score": 1 if int(out.get("score", 0)) == 1 else 0,
            "reason": str(out.get("reason", "")),
        }

    def faithfulness(self, answer: str, context: list[str]) -> dict:
        ctx = "\n\n---\n\n".join(context) or "(no context)"
        out = self._ask(FAITHFULNESS_PROMPT.format(context=ctx, answer=answer))
        claims, sup = int(out.get("claims", 0)), int(out.get("supported", 0))
        score = min(sup, claims) / claims if claims > 0 else None
        return {"score": score, "reason": str(out.get("reason", ""))}


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_IDENT = re.compile(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b")


def key_facts(ground_truth: str) -> list[str]:
    """Numbers/percents (commas and $ stripped) and dashed identifiers (FEE-NSF-02) in the truth."""
    nums = [n.replace(",", "") for n in _NUM.findall(ground_truth)]
    idents = [i.lower() for i in _IDENT.findall(ground_truth)]
    return nums + idents


def key_fact_match(ground_truth: str, answer: str) -> float | None:
    """Fraction of key facts present in the answer; None when the truth has none (e.g. a refusal)."""
    facts = key_facts(ground_truth)
    if not facts:
        return None
    ans = answer.lower().replace(",", "")
    hit = 0
    for f in facts:
        pat = rf"(?<![\d.]){re.escape(f)}(?!\d)" if f[0].isdigit() else re.escape(f)
        hit += bool(re.search(pat, ans))
    return hit / len(facts)
