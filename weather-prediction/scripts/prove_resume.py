"""Proof: a killed run resumes from its checkpoint and does not repeat a finished tool call.

Run: .venv/Scripts/python scripts/prove_resume.py   (make prove-resume)

Uses the real database and the real tools with the offline scripted model, so it needs no API
key. Step 1 starts a child process that asks one question; the model asks for two tools; the
process is killed with os._exit inside the second tool, after the first one finished. Step 2
starts a new process that resumes the same thread. The script then checks agent.tool_call:
the first tool ran once and kept its original finish time, the second ran twice.
"""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime

from langchain_core.messages import AIMessage, ToolMessage

from weatherwise.agent import tools
from weatherwise.agent.graph import build_agent
from weatherwise.agent.scripted import ScriptedModel

CITY = "torrance"
QUESTION = "How warm is tomorrow, and how far off is a day-ahead forecast usually?"


def answer(messages) -> AIMessage:
    """The scripted model's final turn: quote one number from each tool result."""
    got = {m.name: json.loads(m.content) for m in messages if isinstance(m, ToolMessage)}
    day = got["get_outlook"]["rows"][0]
    miss = got["get_forecast_error_by_lead"]["rows"][0]
    return AIMessage(
        content=f"The forecast high for {day['date']} is {day['high_f']} F. Day-ahead published "
        f"forecasts have missed by {miss['published_avg_miss_f']} F on average."
    )


def agent():
    two = AIMessage(
        content="",
        tool_calls=[
            {"name": "get_outlook", "args": {"city": CITY, "days": 1}, "id": "call_1"},
            {
                "name": "get_forecast_error_by_lead",
                "args": {"city": CITY, "variable": "tmax"},
                "id": "call_2",
            },
        ],
    )
    registry = dict(tools.TOOLS)
    real = registry["get_forecast_error_by_lead"]

    def dies_once(ctx, args):
        if os.environ.get("WEATHERWISE_KILL_IN_TOOL"):
            print("[child] killed inside get_forecast_error_by_lead (os._exit 137)", flush=True)
            os._exit(137)
        return real.run(ctx, args)

    registry[real.name] = tools.Tool(
        real.name, real.description, real.args, dies_once, real.temps, real.gaps, real.empty
    )
    return build_agent(model=ScriptedModel(responses=[two, answer]), tools=registry)


def child(thread: str, resume: bool) -> int:
    a = agent()
    out = a.resume(thread) if resume else a.ask(QUESTION, thread)
    a.close()
    print(f"[child] answer: {out['answer']}")
    print(f"[child] model calls {out['model_calls']}, numbers checked: {out['grounded']}")
    return 0


def table(a, thread: str) -> list[dict]:
    with a.pool.connection() as con:
        rows = con.execute(
            "select call_id, tool, status, attempts, row_count, finished_at "
            "from agent.tool_call where thread_id = %s order by started_at",
            [thread],
        ).fetchall()
    for r in rows:
        print(
            f"  {r['call_id']:38s} {r['tool']:28s} {r['status']:8s} attempts={r['attempts']} "
            f"rows={r['row_count']} finished={r['finished_at']}"
        )
    return rows


def main() -> int:
    if len(sys.argv) > 2:
        return child(sys.argv[2], sys.argv[1] == "--resume")
    thread = f"proof-{datetime.now(UTC):%Y%m%dT%H%M%S}"
    print(f"# kill-and-resume proof, thread {thread}, {datetime.now(UTC):%FT%TZ}")
    print(f"question: {QUESTION}")
    me = [sys.executable, __file__]

    print("\n== step 1: run, killed inside the second tool ==")
    env = {**os.environ, "WEATHERWISE_KILL_IN_TOOL": "1"}
    first = subprocess.run([*me, "--ask", thread], env=env, capture_output=True, text=True)
    print(first.stdout.strip())
    print(f"child exit code: {first.returncode}")
    a = agent()
    print("agent.tool_call after the kill:")
    before = table(a, thread)
    state = a.graph.get_state({"configurable": {"thread_id": thread, "user_id": "local"}})
    print(f"checkpoint: next node = {state.next}, messages saved = {len(state.values['messages'])}")

    print("\n== step 2: a new process resumes the same thread ==")
    second = subprocess.run([*me, "--resume", thread], capture_output=True, text=True)
    print(second.stdout.strip())
    print(f"child exit code: {second.returncode}")
    print("agent.tool_call after the resume:")
    after = table(a, thread)
    a.close()

    checks = {
        "first run was killed (exit 137)": first.returncode == 137,
        "checkpoint was waiting at the tools step": state.next == ("tools",),
        "first tool finished before the kill": before[0]["status"] == "ok",
        "second tool was cut off": before[1]["status"] == "running",
        "resume finished (exit 0)": second.returncode == 0,
        "first tool ran once": after[0]["attempts"] == 1,
        "first tool was not rerun (same finish time)": after[0]["finished_at"]
        == before[0]["finished_at"],
        "second tool ran again and finished": (after[1]["status"], after[1]["attempts"])
        == ("ok", 2),
    }
    print("\n== checks ==")
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
