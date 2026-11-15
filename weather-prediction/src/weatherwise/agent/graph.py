"""The planning assistant: a LangGraph state machine over the tools in tools.py.

    route -> model -> tools -> model -> ... -> answer -> (model once more, or end)

route   loads the user's saved preferences and resets the per-question counters
model   one model call; counts it; stops at the per-thread limit; reports a model failure
tools   runs every tool call of the last model turn through tools.run_tool
answer  checks that every number in the answer is in a tool result (grounding.py); asks for
        one rewrite, then replaces the answer with a refusal

State is saved to Postgres after every step (PostgresSaver), keyed by thread id, so a
conversation survives a restart and a killed run resumes where it stopped. Preferences live in
a PostgresStore, keyed by user, so they are shared by all of that user's threads.
"""

import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Any, TypedDict

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.store.postgres import PostgresStore
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from weatherwise import warehouse
from weatherwise.agent import grounding, tools
from weatherwise.config import database_url

log = logging.getLogger("weatherwise.agent")
DEFAULT_MODEL = "claude-opus-5-5"
MAX_MODEL_CALLS = 200  # per thread; WEATHERWISE_MAX_MODEL_CALLS overrides
SYSTEM = """You are the weatherwise planning assistant. You help one person plan around the \
weather using the forecasts and the measured forecast errors stored in this project's database.

How to work
- Every number you state must come from a tool result in this conversation, written exactly \
as the tool returned it (70.3, not 70 or "about 70"). Never estimate, add, subtract, average, \
round or convert numbers yourself. Tool results give temperatures in both C and F; quote the \
unit the user prefers. A checker rejects any answer with a number that is not in a tool result.
- Use the weekday and date columns from tool results to match days the user names. Do not \
work out weekdays yourself.
- If a tool returns no rows or says the data is unavailable, say exactly that. Do not fill the \
gap from general knowledge.
- The forecast numbers are made by statistical models, not by you. You read and explain them.
- When the question is about planning ("should I ...", "will it be ..."), give the forecast \
value, its likely range, and how far off forecasts at that distance have been, then a plain \
recommendation. A range is where the value is likely to fall, not a guarantee.
- Days 8 to 30 are a seasonal expectation with a range. Say so when you use them.
- Keep answers short: the answer first, then the numbers behind it. Plain sentences.
- Save a preference only when the user states one or asks you to remember it."""
REWRITE = (
    "[number check] Your draft was not shown to the user. It contained figures that are not in "
    "any tool result: {bad}. Write the answer again using only numbers that appear in tool "
    "results. If the data does not contain a figure, say so instead of giving one."
)
REFUSAL = (
    "I cannot give that answer: it contained figures that are not in the forecast data I can "
    "read. Ask me for the outlook, the forecast's track record, a day you entered, your "
    "scoreboard or the data health, and I will quote what is stored."
)


STOPPED = {  # stop reasons that mean there is no usable answer: state error, user message
    "refusal": (
        "model declined",
        "The model declined to answer this request, so no answer was produced.",
    ),
    "max_tokens": (
        "answer cut off",
        "The answer was cut off before it was finished, so it is not shown. Ask a "
        "narrower question.",
    ),
    "empty": (
        "empty reply",
        "The model returned nothing, so no answer was produced. Try again.",
    ),
}


class MissingKey(RuntimeError):
    """No ANTHROPIC_API_KEY, so the real model cannot be built."""


class State(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    model_calls: int  # whole thread
    rewrites: int  # this question
    prefs: dict
    error: str | None
    unsupported: list[str]


def claude_model():
    """The real model. The key is read from the environment by the Anthropic SDK; this module
    only checks that one is set."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise MissingKey("Set ANTHROPIC_API_KEY in .env to use the assistant.")
    from langchain_anthropic import ChatAnthropic

    extra = {}
    if os.environ.get("WEATHERWISE_FALLBACKS", "on").lower() != "off":
        # If a safety classifier declines a request, the API retries it on a fallback model.
        extra = {
            "betas": ["server-side-fallback-2026-07-01"],
            "model_kwargs": {"fallbacks": "default"},
        }
    return ChatAnthropic(
        model=os.environ.get("WEATHERWISE_MODEL", DEFAULT_MODEL),
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": os.environ.get("WEATHERWISE_EFFORT", "medium")},
        max_retries=2,  # the SDK retries 429, 5xx and connection errors with backoff
        timeout=120,
        **extra,
    )


def text_of(message: AnyMessage) -> str:
    """Visible text of a message (model replies can be a list of blocks)."""
    if isinstance(message.content, str):
        return message.content
    return "".join(b.get("text", "") for b in message.content if b.get("type") == "text")


def internal(message: AnyMessage) -> bool:
    return bool(message.additional_kwargs.get("internal"))


@dataclass
class Agent:
    pool: ConnectionPool
    store: PostgresStore
    graph: Any
    timeout_s: float = 10.0
    recursion_limit: int = 100
    _locks: dict = field(default_factory=lambda: defaultdict(threading.Lock))

    def context(self, user_id: str) -> tools.Context:
        return tools.Context(self.pool, self.store, user_id, self.timeout_s)

    def _config(self, thread_id: str, user_id: str) -> dict:
        return {
            "configurable": {"thread_id": thread_id, "user_id": user_id},
            "recursion_limit": self.recursion_limit,
        }

    def ask(self, question: str, thread_id: str | None = None, user_id: str = "local") -> dict:
        thread_id = thread_id or uuid.uuid4().hex
        config = self._config(thread_id, user_id)
        with self._locks[thread_id]:  # one question at a time per conversation
            if self.graph.get_state(config).next:
                # An earlier run was cut off mid-step. Finish it first: a new question on
                # top of a tool call with no result would be rejected by the model API.
                self.graph.invoke(None, config, durability="sync")
            state = self.graph.invoke(
                {"messages": [HumanMessage(content=question)]},
                config,
                durability="sync",  # each step is saved before the next starts
            )
        return self._result(thread_id, state)

    def resume(self, thread_id: str, user_id: str = "local") -> dict:
        """Continue a run that stopped part-way (a crash, a kill) from its last checkpoint."""
        config = self._config(thread_id, user_id)
        with self._locks[thread_id]:
            if not self.graph.get_state(config).values.get("messages"):
                raise LookupError(f"no such conversation: {thread_id!r}")
            state = self.graph.invoke(None, config, durability="sync")
        return self._result(thread_id, state)

    def history(self, thread_id: str) -> list[dict]:
        """What the user saw: their questions and the assistant's answers."""
        state = self.graph.get_state(self._config(thread_id, "local")).values
        out = []
        for m in state.get("messages", []):
            if isinstance(m, HumanMessage) and not internal(m):
                out.append({"role": "user", "content": text_of(m)})
            elif isinstance(m, AIMessage) and not m.tool_calls and text_of(m):
                out.append({"role": "assistant", "content": text_of(m)})
        return out

    def _result(self, thread_id: str, state: dict) -> dict:
        messages = state["messages"]
        asked = max(
            i for i, m in enumerate(messages) if isinstance(m, HumanMessage) and not internal(m)
        )
        ids = [
            f"{thread_id}:{c['id']}"
            for m in messages[asked:]
            if isinstance(m, AIMessage)
            for c in m.tool_calls
        ]
        with self.pool.connection() as con:
            calls = con.execute(
                "select tool, args, status, row_count, ms, attempts from agent.tool_call "
                "where call_id = any(%s) order by started_at",
                [ids],
            ).fetchall()
        return {
            "thread_id": thread_id,
            "answer": text_of(messages[-1]),
            "grounded": not state.get("unsupported"),
            "unsupported": state.get("unsupported") or [],
            "rewrites": state.get("rewrites", 0),
            "model_calls": state.get("model_calls", 0),
            "error": state.get("error"),
            "tool_calls": calls,
        }

    def close(self) -> None:
        self.pool.close()


def build_agent(
    url: str | None = None,
    model=None,
    tools: dict[str, tools.Tool] | None = None,
    max_model_calls: int | None = None,
    today: date | None = None,
    sleep=time.sleep,
) -> Agent:
    """Open the pool, create LangGraph's tables if needed and compile the graph. `model`,
    `tools`, `today` and `sleep` are injectable so tests run offline and fast."""
    from weatherwise.agent import tools as toolbox  # the `tools` argument shadows the module

    url = url or database_url()
    with warehouse.connect(url) as con:  # migrations: schema agent, the reader role
        warehouse.grant_reader(con)  # marts built before this role existed
    registry = toolbox.TOOLS if tools is None else tools
    limit = (
        max_model_calls
        if max_model_calls is not None
        else int(os.environ.get("WEATHERWISE_MAX_MODEL_CALLS", MAX_MODEL_CALLS))
    )
    bound = (model or claude_model()).bind_tools(toolbox.schemas(registry))
    pool = ConnectionPool(
        url,
        min_size=1,
        max_size=4,
        open=True,
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
            "prepare_threshold": 0,
            "options": "-c search_path=agent,public",  # LangGraph's tables go to schema agent
        },
    )
    try:
        saver, store = PostgresSaver(pool), PostgresStore(pool)
        saver.setup()
        store.setup()
    except BaseException:
        pool.close()
        raise
    # each model call is at most three graph steps, so the call limit always stops a
    # runaway conversation before LangGraph's own step limit does
    agent = Agent(pool, store, None, recursion_limit=3 * limit + 10)

    def route(state: State, config) -> dict:
        user = config["configurable"]["user_id"]
        return {
            "prefs": toolbox.preferences(store, user),
            "rewrites": 0,
            "error": None,
            "unsupported": [],
        }

    def call_model(state: State) -> dict:
        used = state.get("model_calls", 0)
        if used >= limit:
            note = (
                f"This conversation has reached its limit of {limit} model calls. "
                "Start a new conversation to continue."
            )
            return {"messages": [AIMessage(content=note)], "error": "model call limit reached"}
        prefs = "; ".join(f"{k}: {v}" for k, v in state.get("prefs", {}).items()) or "none saved"
        day = today or date.today()
        system = f"{SYSTEM}\n\nToday is {day:%A} {day.isoformat()}.\nSaved preferences: {prefs}"
        try:
            reply = bound.invoke([SystemMessage(content=system), *state["messages"]])
        except Exception as exc:  # after the SDK's own retries: say so, never guess
            log.error("model call failed: %s: %s", type(exc).__name__, exc)
            rejected = getattr(exc, "status_code", None) in (400, 401, 403, 404)
            note = (
                "The model rejected the request, so no answer was produced. Check the API "
                "key and the model name in .env; the server log has the reason."
                if rejected
                else "The assistant's model could not be reached, so no answer was "
                "produced. Try again in a moment."
            )
            kind = "model rejected the request" if rejected else "model unavailable"
            return {
                "messages": [AIMessage(content=note)],
                "model_calls": used + 1,
                "error": f"{kind}: {type(exc).__name__}",
            }
        reason = reply.response_metadata.get("stop_reason")
        if not reply.tool_calls and not text_of(reply).strip():
            reason = reason if reason in STOPPED else "empty"
        if reason in STOPPED and (reason != "max_tokens" or not reply.tool_calls):
            # the unusable reply is dropped: a cut-off tool call must not stay in the thread
            error, note = STOPPED[reason]
            return {
                "messages": [AIMessage(content=note)],
                "model_calls": used + 1,
                "error": error,
            }
        return {"messages": [reply], "model_calls": used + 1}

    def run_tools(state: State, config) -> dict:
        conf = config["configurable"]
        ctx = agent.context(conf["user_id"])
        out = []
        for c in state["messages"][-1].tool_calls:
            try:
                result = toolbox.run_tool(ctx, conf["thread_id"], c, registry, sleep)
            except Exception as exc:  # the log itself failed (database down): every tool
                # call still gets a result, or the thread could never continue
                log.error("tool %s failed outside its query: %s", c["name"], exc)
                result = {
                    "tool": c["name"],
                    "status": "error",
                    "error": "data unavailable: the database could not be reached. Do not "
                    "estimate; tell the user the data could not be read.",
                }
            result.pop("replayed", None)
            out.append(
                ToolMessage(
                    content=json.dumps(result, sort_keys=True),
                    tool_call_id=c["id"],
                    name=c["name"],
                    status="success" if result["status"] == "ok" else "error",
                )
            )
        return {"messages": out}

    def check_answer(state: State) -> dict:
        messages = state["messages"]
        draft = messages[-1]
        sources = [f"today {(today or date.today()).isoformat()}", json.dumps(state.get("prefs"))]
        for m in messages[:-1]:
            if isinstance(m, ToolMessage) or (isinstance(m, HumanMessage) and not internal(m)):
                sources.append(text_of(m))
            elif isinstance(m, AIMessage):
                sources.extend(json.dumps(c["args"]) for c in m.tool_calls)
        bad = grounding.unsupported(text_of(draft), sources)
        if not bad:
            return {"unsupported": []}
        if state.get("rewrites", 0) < 1:
            note = HumanMessage(
                content=REWRITE.format(bad=", ".join(bad)), additional_kwargs={"internal": True}
            )
            return {"messages": [RemoveMessage(id=draft.id), note], "rewrites": 1}
        return {"messages": [AIMessage(content=REFUSAL, id=draft.id)], "unsupported": bad}

    def after_model(state: State) -> str:
        if state.get("error"):
            return END
        return "tools" if state["messages"][-1].tool_calls else "answer"

    def after_answer(state: State) -> str:
        return "model" if internal(state["messages"][-1]) else END

    g = StateGraph(State)
    g.add_node("route", route)
    g.add_node("model", call_model)
    g.add_node("tools", run_tools)
    g.add_node("answer", check_answer)
    g.add_edge(START, "route")
    g.add_edge("route", "model")
    g.add_conditional_edges("model", after_model, ["tools", "answer", END])
    g.add_edge("tools", "model")
    g.add_conditional_edges("answer", after_answer, ["model", END])
    agent.graph = g.compile(checkpointer=saver, store=store)
    return agent
