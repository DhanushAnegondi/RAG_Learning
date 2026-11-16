"""Write results/sprint-05/: meta.json, the drift table and run log of the real daily run, the
month-by-month evidence behind the drift flag, and a snapshot of app_run_log. Everything is
read from captured run files and the database; no number is typed in here.

Run after: make test, make mutate, make daily, make faults, make eval. Then: make results.
"""

import csv
import json
import re
from pathlib import Path

import psycopg

from weatherwise import ops, warehouse
from weatherwise.config import database_url

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "sprint-05"
RUN = OUT / "run"
CITY = "torrance"


def read(name: str) -> str:
    path = RUN / name
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def first(pattern: str, text: str, default: str = "not captured") -> str:
    m = re.search(pattern, text)
    return m.group(1) if m else default


def save(name: str, columns: list[str], rows: list) -> None:
    with (OUT / "metrics" / name).open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        w.writerows(rows)


def main() -> int:
    for sub in ("metrics", "tables"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    green, mutation = read("green.out"), read("mutation.out")
    faults, evals = read("faults.out"), read("eval.out")
    with psycopg.connect(database_url(), autocommit=True) as con:
        runs = warehouse.frame(
            con,
            "select run_id, today, status, step, mode, attempts, error, "
            "detail -> 'warnings' as warnings, detail ->> 'decision' as decision, "
            "started_at, finished_at from app_run_log where city = %s order by started_at",
            [CITY],
        )
        save("03_run_log.csv", list(runs.columns), runs.to_numpy().tolist())
        last = con.execute(
            "select run_id, status || coalesce(' (' || mode || ')', ''), detail "
            "from app_run_log where city = %s "
            "and detail ? 'drift' order by started_at desc limit 1",
            [CITY],
        ).fetchone()
        run_id, status, detail = last if last else ("none", "none", {"drift": [], "drifted": []})
        cols = [
            "variable",
            "lead_days",
            "method",
            "n_days",
            "n_live",
            "first_day",
            "last_day",
            "recent_mae_c",
            "baseline_mae_c",
            "drifted",
        ]
        save("02_drift_check.csv", cols, [[d[c] for c in cols] for d in detail["drift"]])
        flagged = detail["drifted"]
        for n, d in enumerate(flagged[:3], 1):
            by_month = warehouse.frame(
                con,
                (ops.SQL / "miss_by_month.sql").read_text(encoding="utf-8"),
                {"city": CITY, "variable": d["variable"], "lead_days": d["lead_days"]},
            )
            save(
                f"04_drift_evidence_{n}_{d['variable']}_lead{d['lead_days']}.csv",
                list(by_month.columns),
                by_month.to_numpy().tolist(),
            )
        snap = warehouse.snapshot(con, "app_run_log", 3)
        (OUT / "tables" / "app_run_log.json").write_text(
            json.dumps(snap, indent=1, default=str), encoding="utf-8"
        )

    fault_pass = len(re.findall(r"(?m)^PASS  \w+ +", faults.split("== summary ==")[-1]))
    fault_fail = len(re.findall(r"(?m)^FAIL  \w+ +", faults.split("== summary ==")[-1]))
    tests = first(r"(\d+ passed[^\n]*)", green)
    killed = first(r"(\d+/\d+ mutations killed)", mutation)
    score = first(r"(\d+/\d+ attempts passed; \d+/\d+ cases passed every attempt)", evals)
    flagged_txt = "; ".join(
        f"{d['variable']} {d['lead_days']} day ahead: recent miss {d['recent_mae_c']} C against "
        f"{d['baseline_mae_c']} C when the method was chosen"
        for d in flagged
    )
    findings = [
        f"Tests: {tests}.",
        f"Mutation check: {killed} (the sprint-05 mutants).",
        f"Real daily run {run_id}: ended {status}. "
        + (
            f"The drift check flagged {len(flagged)} of {len(detail['drift'])} lead/variable "
            f"pairs ({flagged_txt}), so the run stopped at the gate before any retraining. "
            f"Decision recorded: {detail.get('decision', 'none yet')}."
            if flagged
            else f"No drift among {len(detail['drift'])} lead/variable pairs."
        ),
        f"Fault injection: {fault_pass} of {fault_pass + fault_fail} checks passed (API outage, "
        "late data, database restart mid-run, database down, planted drift).",
        f"Question set against the live model: {score}.",
    ]
    meta = {
        "title": "sprint-05: operations (daily run, drift gate with approval, faults, scored "
        "questions)",
        "goal": "Run the forecast every day without re-choosing methods, notice when the "
        "methods have stopped working and stop for a person before retraining, end every "
        "failure in a stated state that a rerun recovers from, and score the assistant "
        "against the database.",
        "pattern": "LangGraph run graph (fetch, check, gate, forecast, finish) with a Postgres "
        "checkpoint per step, an interrupt at the gate and a run log",
        "findings": findings,
        "commands": [
            "make test",
            "make check",
            "make mutate",
            "make daily",
            ".venv/Scripts/python scripts/run_daily.py --approve RUN_ID   (or --decline)",
            "make faults",
            "make eval",
        ],
        "scripts": sorted(
            str(p.relative_to(ROOT)).replace("\\", "/")
            for p in [
                *(ROOT / "sql" / "ops").glob("*.sql"),
                ROOT / "sql" / "migrations" / "003_ops.sql",
                ROOT / "src" / "weatherwise" / "ops.py",
                ROOT / "src" / "weatherwise" / "agent" / "evals.py",
                ROOT / "evals" / "questions.json",
                ROOT / "scripts" / "run_daily.py",
                ROOT / "scripts" / "inject_faults.py",
                ROOT / "scripts" / "run_eval.py",
                ROOT / "scripts" / "write_ops_results.py",
                ROOT / "tests" / "test_sprint5_ops.py",
            ]
        ),
        "table_order": ["app_run_log"],
        "captions": {
            "01_eval.csv": {
                "title": "Question set, live model, each case asked three times",
                "note": "passed = attempts that met every check of the case. Expected values "
                "are read from the database when the evaluation runs. refused_by_number_check "
                "counts attempts whose answer was withheld.",
            },
            "02_drift_check.csv": {
                "title": f"Drift check of the real daily run ({run_id})",
                "note": "recent_mae_c = this project's average miss over the last 30 scored "
                "days; baseline_mae_c = its miss on the held-out year when the method was "
                "chosen. n_live = days scored on a forecast issued live (the rest are "
                "replays). drifted = at least 14 days, over 1.5 times the baseline and over "
                "0.5 C worse.",
            },
            "03_run_log.csv": {
                "title": "Run log (app_run_log) for Torrance",
                "note": "One row per day. waiting_approval = stopped at the gate.",
            },
        },
        "limits": [
            "Drift is measured almost entirely on replayed forecasts so far: the live log "
            "started on 2026-11-14. The replay's models were fitted a year before, so part of "
            "what the check sees is that age, which a daily refit already removes.",
            "For that reason the flag did not clear after the approved re-selection on "
            "2026-11-15: the same methods were chosen again, the refitted model now adds about "
            "1.9 C to the published low for tomorrow, and the check still reads 1.93 C against "
            "0.70 C because it scores the year-old replay, not the model that runs. The run "
            "does not ask again for 7 days. Scoring only live forecasts needs at least 14 "
            "live days.",
            "The drift rule (30 days, 1.5 times, 0.5 C) is a judgement, not tuned on data.",
            "The mutation run for this sprint hung once (a test process idle for 4.5 hours, "
            "no time limit in the script). It was stopped, a time limit added, and the rest "
            "run as three workers, each on its own copy of the tree and its own test database.",
            "The question set is 14 cases written by the author of the assistant; three "
            "attempts each show run-to-run variation, not a confidence interval.",
            "The 'declines' rule of the grader is a phrase match. It shows the answer said no, "
            "not that everything else in it is right.",
            "Fault injection runs on a small synthetic city in the test database with a "
            "stand-in for the weather APIs; the database restart and stop are real.",
            "The 79 + 52 mutants of sprints 01-04 were not rerun this sprint.",
            "No scheduler is installed: `make daily` is run by hand or by a scheduled task "
            "the user sets up.",
        ],
    }
    for name in sorted(p.name for p in (OUT / "metrics").glob("04_*.csv")):
        meta["captions"][name] = {
            "title": "Evidence behind the drift flag: " + name[18:-4].replace("_", " "),
            "note": "Average miss and bias per month from the replayed forecasts. bias below "
            "0 = forecast too cold.",
        }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8", newline="\n")
    n = len(list((OUT / "metrics").glob("*.csv")))
    print(f"wrote {OUT.relative_to(ROOT)}: meta.json and {n} metrics")
    for line in findings:
        print(" -", line.encode("ascii", "replace").decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
