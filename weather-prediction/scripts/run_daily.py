"""The daily run: fetch, check, (gate), forecast.

Run:  .venv/Scripts/python scripts/run_daily.py              (make daily)
      .venv/Scripts/python scripts/run_daily.py --approve torrance-2026-11-16
      .venv/Scripts/python scripts/run_daily.py --decline torrance-2026-11-16

A normal run issues today's forecast with the methods already in use. If the recent forecasts
have drifted from how those methods scored when they were chosen, the run stops and waits:
--approve chooses the methods again (a few minutes), --decline forecasts with the current ones.
Running it again after a failure makes a new attempt from the first step.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import psycopg
from psycopg_pool import PoolTimeout

from weatherwise import ops, pipeline
from weatherwise.config import CITIES, load_env

ROOT = Path(__file__).resolve().parents[1]


def show(row: dict) -> None:
    print(f"run {row['run_id']}: {row['status']} at step {row['step']}, attempt {row['attempts']}")
    if row["mode"]:
        print(f"  mode: {row['mode']}")
    if row["error"]:
        print(f"  error: {row['error']}")
    detail = row["detail"]
    for w in detail.get("warnings", []):
        print(f"  warning: {w}")
    if "snoozed" in detail:
        print(f"  note: {detail['snoozed']}")
    if "decision" in detail:
        print(f"  decision at the gate: {detail['decision']}")
    if detail.get("drift"):
        print("  drift check (recent average miss against the miss when the method was chosen):")
        print("    variable lead method     days live  recent  stored  drifted")
        for d in detail["drift"]:
            print(
                f"    {d['variable']:8s} {d['lead_days']:4d} {d['method']:9s} {d['n_days']:5d} "
                f"{d['n_live']:4d} {d['recent_mae_c']:7.3f} {d['baseline_mae_c'] or 0:7.3f}  "
                f"{'YES' if d['drifted'] else 'no'}"
            )
    if row["status"] == "waiting_approval":
        print(f"  waiting for you: --approve {row['run_id']}  or  --decline {row['run_id']}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--city", default="torrance", choices=sorted(CITIES))
    p.add_argument("--today", type=date.fromisoformat, help="default: today in the city")
    p.add_argument("--approve", metavar="RUN_ID")
    p.add_argument("--decline", metavar="RUN_ID")
    p.add_argument("--no-lstm", action="store_true", help="skip the LSTM (faster, tests)")
    a = p.parse_args()
    load_env()
    try:
        runner = ops.DailyRunner(use_lstm=not a.no_lstm, data_dir=ROOT / "data")
    except (psycopg.OperationalError, PoolTimeout) as exc:
        print(f"The database is not reachable (try: make up). {str(exc).splitlines()[0]}")
        return 2
    try:
        if a.approve or a.decline:
            row = runner.decide(a.approve or a.decline, approve=bool(a.approve))
        else:
            city = CITIES[a.city]
            row = runner.run(city, a.today or pipeline.city_today(city))
    except (LookupError, ValueError, ops.Busy) as exc:
        print(exc)
        return 2
    finally:
        runner.close()
    show(row)
    return {"ok": 0, "waiting_approval": 3}.get(row["status"], 1)


if __name__ == "__main__":
    sys.exit(main())
