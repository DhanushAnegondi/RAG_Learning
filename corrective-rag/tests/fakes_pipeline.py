"""A routing fake chat model for graph/pipeline tests: one object serves grading (structured),
query rewriting and generation, and counts calls per purpose."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .fakes import Reply


class PipelineChat:
    def __init__(
        self,
        *,
        is_relevant: Callable[[str], bool] = lambda text: True,
        answer: str = "The answer is in the documents [1].",
        rewrite: str = "rewritten web query",
        grade_error: Exception | None = None,
        generate_error: Exception | None = None,
        rewrite_error: Exception | None = None,
    ):
        self.is_relevant = is_relevant
        self.answer = answer
        self.rewrite = rewrite
        self.grade_error = grade_error
        self.generate_error = generate_error
        self.rewrite_error = rewrite_error
        self.grade_calls = 0
        self.generate_calls = 0
        self.rewrite_calls = 0
        self.generate_messages: Any = None
        self.grade_prompts: list[str] = []

    def with_structured_output(self, schema: Any) -> Any:
        outer = self

        class _S:
            def invoke(self, messages: Any) -> Any:
                outer.grade_calls += 1
                outer.grade_prompts.append(messages[-1][1])
                if outer.grade_error:
                    raise outer.grade_error
                return schema(relevant=outer.is_relevant(messages[-1][1]))

        return _S()

    def invoke(self, messages: Any) -> Any:
        system = messages[0][1]
        if "search query" in system:
            self.rewrite_calls += 1
            if self.rewrite_error:
                raise self.rewrite_error
            return Reply(self.rewrite)
        self.generate_calls += 1
        self.generate_messages = messages
        if self.generate_error:
            raise self.generate_error
        return Reply(self.answer)
