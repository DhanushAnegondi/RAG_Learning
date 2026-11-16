"""Fault injection for the daily run: break it three ways and state where each one ends.

Run: .venv/Scripts/python scripts/inject_faults.py   (make faults)

Works on the TEST database with a small synthetic city and a stand-in for the weather APIs, so
no real forecast is written. The database restart and stop are real: the Compose service is
restarted in the middle of a run and then stopped for a whole attempt. That service also
hosts the real database, which is therefore unreachable for those seconds; do not run this
while a real daily run or the site is in use.

1. API outage      the fetch step raises after its retries
2. Late data       the APIs answer, but the actuals stop one day, then two days, early
3. Database restart  `docker compose restart db` between the fetch and the check step
4. Drift           recent forecasts made 3 C worse; the run must wait for a decision

Each case prints the run's row in app_run_log and the checks it must satisfy.
"""

import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from conftest import TEST_URL, fresh_db  # noqa: E402
from test_sprint3_review import TODAY, seed_small_city  # noqa: E402

from weatherwise import ingest, ops, pipeline, warehouse  # noqa: E402
from weatherwise.config import City  # noqa: E402

CITY = City("t", 0.0, 0.0, "UTC")
pipeline.SHORT_LEADS, pipeline.HORIZON = 2, 10  # the small city has two leads
RESULTS: list[tuple[str, str, bool]] = []
DOCKER = ["docker", "compose"]


def apis(actual_through=None, then=None):
    """The fetch step: actuals up to yesterday (or `actual_through`) and today's live forecast."""

    def fetch(con, city, today):
        last = con.execute("select max(date) from raw_actual_daily").fetchall()[0][0]
        days = pd.date_range(
            last + timedelta(days=1), actual_through or today - timedelta(days=1), freq="D"
        )
        if len(days):
            new = {
                "city": city.name,
                "date": days,
                "tmax_c": 21.0,
                "tmin_c": 13.0,
                "precip_mm": 0.0,
            }
            warehouse.load(con, "actual_daily", pd.DataFrame(new))
        ahead = pd.date_range(today + timedelta(days=1), periods=6, freq="D")
        live = {
            "city": city.name,
            "issued_on": pd.Timestamp(today),
            "date": ahead,
            "tmax_c": 24.0,
            "tmin_c": 16.0,
            "precip_mm": 0.0,
        }
        warehouse.load(con, "live_forecast", pd.DataFrame(live))
        if then:
            then()

    return fetch


def run(fetch, today):
    r = ops.DailyRunner(TEST_URL, fetch=fetch, use_lstm=False)
    try:
        return r.run(CITY, today)
    finally:
        r.close()


def show(row: dict) -> None:
    print(
        f"  app_run_log: {row['run_id']}  status={row['status']}  step={row['step']}  "
        f"mode={row['mode']}  attempts={row['attempts']}"
    )
    if row["error"]:
        print(f"               error: {row['error']}")
    for w in row["detail"].get("warnings", []):
        print(f"               warning: {w}")


def check(case: str, name: str, ok: bool) -> None:
    RESULTS.append((case, name, bool(ok)))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")


def live_count(day) -> int:
    with psycopg.connect(TEST_URL) as con:
        return con.execute(
            "select count(*) from log_forecast where kind = 'live' and issued_on = %s", [day]
        ).fetchall()[0][0]


def wait_for_database(limit_s: int = 600) -> float:
    start = time.monotonic()
    while time.monotonic() - start < limit_s:
        try:
            psycopg.connect(TEST_URL, connect_timeout=3).close()
            return time.monotonic() - start
        except psycopg.OperationalError:
            time.sleep(2)
    raise RuntimeError("the database did not come back")


def main() -> int:
    print(f"# fault injection, {datetime.now(UTC):%FT%TZ}, database weatherwise_test")
    con = fresh_db()
    seed_small_city(con)
    con.close()
    first = run(apis(), TODAY)
    print("\n== 0. baseline: first run chooses the methods ==")
    show(first)
    check(
        "baseline",
        "first run ends ok and chooses methods",
        (first["status"], first["mode"]) == ("ok", "reselect"),
    )
    day = TODAY

    print("\n== 1. API outage ==")
    day += timedelta(days=1)

    def down(con, city, today):
        raise ingest.IngestError("HTTP 503 from archive-api.open-meteo.com after 4 tries")

    with psycopg.connect(TEST_URL) as c:
        before = warehouse.checksum(c)
    row = run(down, day)
    show(row)
    with psycopg.connect(TEST_URL) as c:
        same = warehouse.checksum(c) == before
    check(
        "outage",
        "run is failed at the fetch step, with the reason",
        (row["status"], row["step"]) == ("failed", "fetch") and "503" in row["error"],
    )
    check("outage", "no data changed and no forecast was issued", same and live_count(day) == 0)
    row = run(apis(), day)
    show(row)
    check(
        "outage",
        "rerun after the outage ends ok on attempt 2",
        (row["status"], row["attempts"]) == ("ok", 2) and live_count(day) == 20,
    )

    print("\n== 2. late data ==")
    newest = day - timedelta(days=1)  # actuals stop here from now on
    day += timedelta(days=1)
    row = run(apis(actual_through=newest), day)
    show(row)
    check(
        "late",
        "one day late: forecast issued, warning recorded",
        row["status"] == "ok"
        and row["detail"]["warnings"] == ["actuals are 1 day behind"]
        and live_count(day) == 20,
    )
    day += timedelta(days=1)
    row = run(apis(actual_through=newest), day)
    show(row)
    check(
        "late",
        "two days late: run failed at the check step, no forecast",
        (row["status"], row["step"]) == ("failed", "check")
        and "StaleData" in row["error"]
        and live_count(day) == 0,
    )
    row = run(apis(), day)
    show(row)
    check(
        "late",
        "when the data arrives the same run ends ok",
        (row["status"], row["attempts"]) == ("ok", 2) and live_count(day) == 20,
    )

    print("\n== 3a. database restart in the middle of a run ==")
    day += timedelta(days=1)

    def restart():
        print("  [fault] docker compose restart db", flush=True)
        subprocess.run([*DOCKER, "restart", "db"], cwd=ROOT, check=True, capture_output=True)

    r = ops.DailyRunner(TEST_URL, fetch=apis(then=restart), use_lstm=False)
    try:
        row, crashed = r.run(CITY, day), None
    except psycopg.Error as exc:  # the run log itself could not be written
        row, crashed = None, f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
    finally:
        r.close()
    print(f"  database reachable again after {wait_for_database():.0f} s")
    with psycopg.connect(TEST_URL) as c:
        after = c.execute(
            "select status, step, attempts from app_run_log where run_id = %s", [f"t-{day}"]
        ).fetchall()
    print(f"  app_run_log after the restart: {after}  (exception: {crashed})")
    status = after[0][0] if after else "no row"
    check(
        "restart",
        "the run is never marked ok without its forecast",
        status != "ok" or live_count(day) == 20,
    )
    if status == "ok":
        print("  the run finished: the pool waited for the database to come back")
    else:
        print(f"  the run did not finish ({status}); running it again")
        row = run(apis(), day)
        show(row)
        status = row["status"]
    check(
        "restart",
        "the day ends ok with exactly one forecast",
        status == "ok" and live_count(day) == 20,
    )

    print("\n== 3b. database down for the whole attempt ==")
    day += timedelta(days=1)
    print("  [fault] docker compose stop db", flush=True)
    subprocess.run([*DOCKER, "stop", "db"], cwd=ROOT, check=True, capture_output=True)
    try:
        run(apis(), day)
        outcome = "the run started"
    except psycopg.OperationalError as exc:
        outcome = f"OperationalError: {str(exc).splitlines()[0]}"
    finally:  # whatever happened above, do not leave the database stopped
        subprocess.run([*DOCKER, "start", "db"], cwd=ROOT, check=True, capture_output=True)
    print(f"  starting a run: {outcome}")
    print(f"  [repair] docker compose start db; reachable after {wait_for_database():.0f} s")
    with psycopg.connect(TEST_URL) as c:
        rows = c.execute(
            "select count(*) from app_run_log where run_id = %s", [f"t-{day}"]
        ).fetchall()
    check(
        "down",
        "the run refused to start, said why, and left no half-made run",
        outcome.startswith("OperationalError") and rows == [(0,)] and live_count(day) == 0,
    )
    row = run(apis(), day)
    show(row)
    check(
        "down",
        "once the database is back the run ends ok",
        row["status"] == "ok" and live_count(day) == 20,
    )

    print("\n== 4. drift: recent forecasts 3 C worse than when the methods were chosen ==")
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        c.execute(
            "update log_forecast set pred_c = pred_c + 3 where lead_days <= 2 and kind = 'hindcast'"
        )
        chosen = c.execute(
            "select variable, lead_days, method from app_model_eval where chosen order by 1, 2"
        ).fetchall()
    day += timedelta(days=1)
    r = ops.DailyRunner(TEST_URL, fetch=apis(), use_lstm=False)
    try:
        row = r.run(CITY, day)
        show(row)
        flagged = [
            (d["variable"], d["lead_days"], d["recent_mae_c"], d["baseline_mae_c"])
            for d in row["detail"]["drifted"]
        ]
        print(f"  drifted (variable, lead, recent miss, stored miss): {flagged}")
        with psycopg.connect(TEST_URL) as c:
            still = c.execute(
                "select variable, lead_days, method from app_model_eval where chosen order by 1, 2"
            ).fetchall()
        check(
            "drift",
            "run waits at the gate; nothing retrained, nothing forecast",
            row["status"] == "waiting_approval" and still == chosen and live_count(day) == 0,
        )
        row = r.decide(row["run_id"], approve=True)
        show(row)
        with psycopg.connect(TEST_URL) as c:
            after = ops.drift(c, "t")
            left = [d for d in after if d["drifted"]] if after else ["no rows"]
        check(
            "drift",
            "after approval the methods are chosen again and drift is gone",
            (row["status"], row["mode"], row["detail"]["decision"])
            == ("ok", "reselect", "approved")
            and not left
            and live_count(day) == 20,
        )
    finally:
        r.close()

    print("\n== summary ==")
    for case, name, ok in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {case:8s} {name}")
    return 0 if all(ok for _, _, ok in RESULTS) else 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONWARNINGS", "ignore")
    raise SystemExit(main())
