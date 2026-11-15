"""An offline stand-in for the model, for tests and the crash-and-resume proof.

It replies from a fixed list. Which entry it uses depends only on the conversation it is given
(how many model turns and correction notes it already holds), never on memory inside the
object, so a new process resuming a thread picks up at the right place.
"""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def call(name: str, args: dict, call_id: str, ai: bool = False):
    """A tool call, or (ai=True) a model turn that makes just that call."""
    tc = {"name": name, "args": args, "id": call_id, "type": "tool_call"}
    return AIMessage(content="", tool_calls=[tc]) if ai else tc


class ScriptedModel(BaseChatModel):
    responses: list[Any]  # AIMessage, or a function(messages) -> AIMessage

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        turn = sum(
            isinstance(m, AIMessage) or bool(m.additional_kwargs.get("internal")) for m in messages
        )
        if turn >= len(self.responses):
            raise RuntimeError(f"scripted model has no reply number {turn + 1}")
        reply = self.responses[turn]
        if callable(reply):
            reply = reply(messages)
        return ChatResult(generations=[ChatGeneration(message=reply.model_copy())])
