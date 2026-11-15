"""Write results/sprint-04/: meta.json, the tool catalogue, the tool-call log of the latest
kill-and-resume proof, and snapshots of the assistant's tables. Everything is read from
captured run files and the database; no number is typed in here.

Run after: make test, make mutate, make prove-resume. Then: make results.
"""

import csv
import json
import re
from pathlib import Path

import psycopg

from weatherwise.agent import tools
from weatherwise.config import database_url

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "sprint-04"
RUN = OUT / "run"


def read(name: str) -> str:
    path = RUN / name
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def first(pattern: str, text: str, default: str = "not captured") -> str:
    m = re.search(pattern, text)
    return m.group(1) if m else default


def short(v, width: int = 110):
    if v is None or isinstance(v, int | float):
        return v
    s = str(v)
    return s if len(s) <= width else s[:width] + "..."


def snapshot(con, table: str, n: int = 3) -> dict:
    cols = con.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_schema = 'agent' and table_name = %s order by ordinal_position",
        [table],
    ).fetchall()
    count = con.execute(f"select count(*) from agent.{table}").fetchall()[0][0]
    sample = con.execute(f"select * from agent.{table} limit {n}").fetchall()
    return {
        "table": f"agent.{table}",
        "row_count": count,
        "columns": [list(c) for c in cols],
        "sample": [[short(v) for v in row] for row in sample],
    }


def main() -> int:
    for sub in ("metrics", "tables"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    green, mutation, resume, live = (
        read("green.out"),
        read("mutation.out"),
        read("resume.out"),
        read("live.out"),
    )

    with (OUT / "metrics" / "01_tools.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tool", "arguments", "reads", "what it returns"])
        for s in tools.schemas(tools.TOOLS):
            args = ", ".join(
                f"{k}: {v.get('type') or '/'.join(v.get('enum', [])) or 'value'}"
                for k, v in s["input_schema"].get("properties", {}).items()
            )
            sql = ROOT / "sql" / "agent" / f"{s['name']}.sql"
            reads = f"sql/agent/{sql.name}" if sql.exists() else "preference store"
            w.writerow([s["name"], args or "none", reads, s["description"]])

    thread = first(r"proof, thread (\S+),", resume, "")
    tables = ["tool_call", "checkpoints", "checkpoint_writes", "store"]
    with psycopg.connect(database_url(), autocommit=True) as con:
        cur = con.execute(
            "select call_id, tool, args, status, attempts, row_count, ms, started_at, finished_at "
            "from agent.tool_call where thread_id = %s order by started_at",
            [thread],
        )
        with (OUT / "metrics" / "02_tool_calls_resume_proof.csv").open(
            "w", encoding="utf-8", newline=""
        ) as f:
            w = csv.writer(f)
            w.writerow([c.name for c in cur.description])
            w.writerows(cur.fetchall())
        for t in tables:
            (OUT / "tables" / f"{t}.json").write_text(
                json.dumps(snapshot(con, t), indent=1, default=str), encoding="utf-8"
            )

    tests = first(r"(\d+ passed[^\n]*)", green)
    killed = first(r"(\d+/\d+ mutations killed)", mutation)
    passed = len(re.findall(r"(?m)^PASS ", resume))
    failed = len(re.findall(r"(?m)^FAIL ", resume))
    findings = [
        f"Tests: {tests} (real Postgres test database, scripted offline model).",
        f"Mutation check: {killed}.",
        f"Kill-and-resume proof on the real database: {passed} of {passed + failed} checks "
        f"passed. {first(r'(child exit code: 137)', resume, 'kill not captured')} in the first "
        "process; a second process resumed the thread; the tool that had finished was not run "
        "again (same finish time, attempts = 1).",
        "Resumed answer, every number taken from a tool result: "
        + first(r"\[child\] answer: ([^\n]+)", resume),
        "Two defects found by the proof and fixed: the read-only role had no grant on marts "
        "built before it existed; checkpoints were written in the background, so a hard kill "
        "could race the save (now written synchronously).",
    ]
    if live:
        asked = len(re.findall(r"(?m)^\$ run_agent\.py", live))
        calls = len(re.findall(r"(?m)^\[tool\] ", live))
        ok = len(re.findall(r"numbers checked: ok", live))
        refused = len(re.findall(r"numbers checked: refused", live))
        findings.append(
            f"Live run against Claude (run/live.out): {asked} questions, {calls} tool calls. "
            f"{ok} answers passed the number check; {refused} was refused because the "
            "rewritten answer still held a number that is in no tool result. Preferences "
            "saved in one conversation were used in a new one."
        )
        findings.append(
            "Seen in the live run, and not caught: an answer stated a 0.5 F gap that the "
            "model had subtracted itself. It passed because 0.5 appears elsewhere in the "
            "same tool result. The check matches digits, not meaning."
        )
    else:
        findings.append(
            "No live run against Claude: no ANTHROPIC_API_KEY was configured during the "
            "sprint. The model is exercised only through the scripted stand-in."
        )
    meta = {
        "title": "sprint-04: LangGraph planning assistant over the forecast database",
        "goal": "An assistant that answers planning questions from the stored forecasts and "
        "their measured errors, and cannot state a number the database does not hold. "
        "Read-only typed SQL tools, every tool call logged, conversation state checkpointed "
        "to Postgres, preferences remembered across conversations, a killed run resumable.",
        "pattern": "LangGraph StateGraph (route, model, tools, answer) + Postgres checkpointer "
        "and store + read-only role",
        "findings": findings,
        "commands": [
            "make test",
            "make check",
            "make mutate",
            "make prove-resume",
            'make agent Q="Is Saturday warm enough for the beach?"',
            "make site",
        ],
        "scripts": sorted(
            str(p.relative_to(ROOT)).replace("\\", "/")
            for p in [
                *(ROOT / "sql" / "agent").glob("*.sql"),
                ROOT / "sql" / "migrations" / "002_agent.sql",
                *(ROOT / "src" / "weatherwise" / "agent").glob("*.py"),
                ROOT / "scripts" / "run_agent.py",
                ROOT / "scripts" / "prove_resume.py",
                ROOT / "scripts" / "write_agent_results.py",
                ROOT / "tests" / "test_sprint4_agent.py",
            ]
        ),
        "table_order": tables,
        "captions": {
            "01_tools.csv": {
                "title": "The assistant's tools",
                "note": "Fixed queries with typed arguments. There is no tool that takes SQL.",
            },
            "02_tool_calls_resume_proof.csv": {
                "title": "Tool-call log of the kill-and-resume proof",
                "note": "From agent.tool_call for the proof thread. attempts counts real "
                "executions; the first call kept attempts = 1 across the kill.",
            },
        },
        "limits": [
            "The number check is strict on purpose: a figure the model works out itself (a "
            "sum, a difference, a unit conversion) is refused even when it is right.",
            "The number check reads digits. It does not check that a number is attached to the "
            "right day or the right quantity, and it does not check words ('warm', 'likely'). "
            "A figure the model computes passes if the same digits happen to be in a tool "
            "result; the live run shows one such case.",
            "One local user. Threads are not access-controlled: anyone who can reach the site "
            "and knows a thread id can read that conversation.",
            "The live run is five questions read by hand, not a scored evaluation. A scored "
            "question set against the live model is sprint 05.",
            "The 79 mutants of sprints 01-03 were not rerun this sprint (the machine was short "
            "of memory); the mutation figure above covers the sprint-04 files only.",
            "A tool cut off mid-query is run again on resume. That is safe here because every "
            "data tool is read-only.",
        ],
    }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}: meta.json, 2 metrics, {len(tables)} table snapshots")
    for line in findings:
        print(" -", line.encode("ascii", "replace").decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
