"""Score the assistant against the database on the fixed question set (evals/questions.json).

Run: .venv/Scripts/python scripts/run_eval.py   (make eval)

Needs ANTHROPIC_API_KEY in .env: every question is put to the live model, --repeats times
(default 3), because the same question does not always get the same answer. Each attempt runs
in its own conversation, as its own user, so saved preferences cannot leak between cases.
Writes results/<sprint>/metrics/01_eval.csv and prints every attempt, including any draft the
number check turned down.
"""

import argparse
import csv
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from weatherwise.agent import evals
from weatherwise.agent.graph import DEFAULT_MODEL, MissingKey, build_agent
from weatherwise.config import database_url, load_env

ROOT = Path(__file__).resolve().parents[1]


def flat(text: str, width: int = 420) -> str:
    return " ".join(text.split())[:width].encode("ascii", "replace").decode()


def attempt(agent, case: dict, question: str, want: list, name: str) -> dict:
    """One fresh conversation for one case; returns the verdict with what was seen."""
    if case.get("setup"):
        agent.ask(case["setup"], name, name)
    out = agent.ask(question, name, name)
    verdict = evals.grade({**case, "expect": want, "asked": question}, out)
    tools = " ".join(c["tool"] for c in out["tool_calls"]) or "-"
    check = "ok" if out["grounded"] else f"refused {out['unsupported']}"
    print(f"  {'PASS' if verdict['passed'] else 'FAIL'}  {verdict['why']}")
    print(f"        tools: {tools}; number check: {check}; model calls: {out['model_calls']}")
    print(f"        A: {flat(out['answer'])}")
    for n, r in enumerate(out["rejected"], 1):
        print(
            f"        rejected draft {n} (never shown), over {r['unsupported']}: {flat(r['draft'])}"
        )
    return {**verdict, "tools": tools, "refused": not out["grounded"], "calls": out["model_calls"]}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sprint", default="sprint-05")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--only", nargs="*", help="case ids to run (results are not saved)")
    a = p.parse_args()
    load_env()
    spec = json.loads((ROOT / "evals" / "questions.json").read_text(encoding="utf-8"))
    try:
        agent = build_agent()
    except MissingKey as exc:
        print(exc)
        return 2
    stamp = f"{datetime.now(UTC):%Y%m%dT%H%M%S}"
    model = os.environ.get("WEATHERWISE_MODEL", DEFAULT_MODEL)
    effort = os.environ.get("WEATHERWISE_EFFORT", "medium")
    print(
        f"# question set, {datetime.now(UTC):%FT%TZ}, {len(spec['cases'])} cases x "
        f"{a.repeats} attempts, model {model}, effort {effort} (no sampling settings: "
        "the API takes none for this model)"
    )
    rows, skipped = [], []
    try:
        with psycopg.connect(database_url(), autocommit=True) as con:
            _, params = evals.fill("", con, spec["params_sql"], {})
            print(f"# outlook issued {params['issued']}; first day {params['d1']}")
            for case in spec["cases"]:
                if a.only and case["id"] not in a.only:
                    continue
                skip = case.get("only_if_sql")
                if skip and not con.execute(skip).fetchall()[0][0]:
                    print(f"\nSKIP  {case['id']}: its precondition does not hold in this database")
                    skipped.append(case["id"])
                    continue
                question = case["question"].format(**params)
                try:
                    want = evals.expected(con, case, params)
                except LookupError as exc:  # the key cannot be read: the case fails
                    print(f"\n{case['id']}: FAIL  {exc}")
                    rows.append(
                        {
                            "case": case["id"],
                            "checks": case["checks"],
                            "passed": f"0/{a.repeats}",
                            "failures": str(exc),
                            "refused_by_number_check": 0,
                            "expected": "unreadable",
                            "tools_used": "-",
                            "model_calls": 0,
                        }
                    )
                    continue
                key = " ".join(str(w["value"]) for w in want)
                print(f"\n{case['id']}: {question}")
                print(f"  expected: {key or 'no figure for what was asked'}")
                tries = [
                    attempt(agent, case, question, want, f"eval-{stamp}-{case['id']}-{n}")
                    for n in range(1, a.repeats + 1)
                ]
                passed = sum(t["passed"] for t in tries)
                rows.append(
                    {
                        "case": case["id"],
                        "checks": case["checks"],
                        "passed": f"{passed}/{len(tries)}",
                        "failures": "; ".join(sorted({t["why"] for t in tries if not t["passed"]})),
                        "refused_by_number_check": sum(t["refused"] for t in tries),
                        "expected": key or "no figure",
                        "tools_used": tries[0]["tools"],
                        "model_calls": sum(t["calls"] for t in tries),
                    }
                )
    finally:
        agent.close()
    done = sum(int(r["passed"].split("/")[0]) for r in rows)
    total = sum(int(r["passed"].split("/")[1]) for r in rows)
    clean = sum(r["passed"].split("/")[0] == r["passed"].split("/")[1] for r in rows)
    print("\n== score ==")
    for r in rows:
        print(f"{r['passed']}  {r['case']}" + (f"  ({r['failures']})" if r["failures"] else ""))
    print(f"\n{done}/{total} attempts passed; {clean}/{len(rows)} cases passed every attempt")
    if skipped:
        print(f"not run (precondition did not hold): {', '.join(skipped)}")
    if rows and not a.only:
        out_dir = ROOT / "results" / a.sprint / "metrics"
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / "01_eval.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return 0 if rows and done == total else 1


if __name__ == "__main__":
    sys.exit(main())
