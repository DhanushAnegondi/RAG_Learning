"""Ask the planning assistant from the terminal.

Run: .venv/Scripts/python scripts/run_agent.py "Should I plan a beach day this weekend?"
     add --thread ID to continue a conversation, --resume ID to finish a run that was cut off.
Needs ANTHROPIC_API_KEY in .env (make agent Q="...").
"""

import argparse
import sys

import psycopg

from weatherwise.agent.graph import MissingKey, build_agent
from weatherwise.config import load_env


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("question", nargs="?")
    p.add_argument("--thread", help="thread id to continue")
    p.add_argument("--resume", metavar="THREAD", help="finish an interrupted run")
    a = p.parse_args()
    if not a.question and not a.resume:
        p.error("give a question, or --resume THREAD")
    load_env()
    try:
        agent = build_agent()
    except MissingKey as exc:
        print(exc)
        return 2
    except psycopg.OperationalError as exc:
        print(f"The database is not reachable (try: make up). {str(exc).splitlines()[0]}")
        return 2
    try:
        out = agent.resume(a.resume) if a.resume else agent.ask(a.question, a.thread)
    finally:
        agent.close()
    for c in out["tool_calls"]:
        print(
            f"[tool] {c['tool']} {c['args']} -> {c['status']}, {c['row_count']} rows, {c['ms']} ms"
        )
    print(out["answer"].encode("ascii", "replace").decode())
    print(
        f"[thread {out['thread_id']}] model calls {out['model_calls']}, "
        f"numbers checked: {'ok' if out['grounded'] else 'refused ' + str(out['unsupported'])}"
    )
    return 1 if out["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
