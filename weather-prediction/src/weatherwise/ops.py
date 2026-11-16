"""Operations: the daily run.

    fetch -> check -> gate -> forecast -> finish

fetch     new actuals, archived forecasts and today's live forecast (pipeline.fetch_all)
check     rebuild the SQL models; stop if the newest actuals are too old or have a hole;
          measure drift
gate      if drift was found and nobody has decided recently, stop and wait for a person
          (LangGraph interrupt)
forecast  issue today's forecast with the methods of the last selection, or, after an
          approval or on a first run, choose the methods again (pipeline.run_city); then
          back up what cannot be rebuilt
finish    mark the run ok

Rules the code keeps:
- One run at a time. A Postgres advisory lock is held for the whole run; a second run started
  meanwhile is refused. A killed process lets go of the lock by dying.
- A run is for today. A day the loaded actuals have already reached is refused, and a run
  left waiting is closed when a later day starts: forecasting "for the past" with newer data
  would write a live forecast made with hindsight, and live forecasts are never rewritten.
- A decision is kept. If a run fails after it was approved or declined, the next attempt does
  not ask again; and after any decision the gate does not ask again for SNOOZE_DAYS.
- The run log tells the truth. One row per run in app_run_log: running, waiting_approval, ok
  or failed, with the step, the reason and the numbers behind a decision. A row that is ok is
  never changed again.

The graph is checkpointed to Postgres after every step so that a run waiting at the gate can
be answered later, by another process. A run that failed or was killed is attempted again from
the first step; every step is safe to repeat. SQL lives in sql/ops/.
"""

import json
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TypedDict

import pandas as pd
import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from psycopg.rows import dict_row

from weatherwise import models, pipeline, warehouse
from weatherwise.agent.graph import open_pool
from weatherwise.config import CITIES, City, database_url

SQL = warehouse.SQL_DIR / "ops"
RECENT_DAYS = 30  # drift looks at this many scored days
MIN_DAYS = 14  # and needs at least this many
RATIO = 1.5  # recent miss must be over this many times the stored one
MIN_GAP_C = 0.5  # and worse by more than this
SNOOZE_DAYS = 7  # after a decision at the gate, do not ask again for this long
# lag = days the newest actual is behind yesterday. The models need an observation at most
# MAX_OBS_AGE_DAYS old, which is a lag of one day: allowed, with a warning. More stops the run.
MAX_LAG = models.MAX_OBS_AGE_DAYS - 1
RUN_LOCK = 7312005  # pg_advisory_lock key: one daily run at a time


class StaleData(RuntimeError):
    """The newest actuals are too old, or have a hole, to forecast from."""


class Busy(RuntimeError):
    """Another daily run holds the lock."""


class State(TypedDict, total=False):
    run_id: str
    city: str
    today: str
    lag_days: int
    warnings: list[str]
    drift: list[dict]
    drifted: list[dict]
    mode: str  # forecast | reselect
    decision: str  # approved | declined: given at the gate, or carried from an earlier attempt
    snoozed: str  # why the gate did not ask although drift was found


def _sql(name: str) -> str:
    return (SQL / f"{name}.sql").read_text(encoding="utf-8")


def drift(con: psycopg.Connection, city: str) -> list[dict]:
    """One row per variable and corrected lead: recent average miss against the stored one."""
    params = {
        "city": city,
        "max_lead": pipeline.SHORT_LEADS,
        "days": RECENT_DAYS,
        "min_days": MIN_DAYS,
        "ratio": RATIO,
        "gap": MIN_GAP_C,
    }
    return warehouse.frame(con, _sql("drift"), params).to_dict("records")


def data_lag(con: psycopg.Connection, city: str, today: date) -> tuple[int | None, int]:
    """(days the newest usable actual is behind yesterday, usable days among the last WINDOW
    calendar days up to it). The lag is None when there are no actuals at all."""
    params = {"city": city, "today": today, "window": pipeline.WINDOW}
    lag, recent = con.execute(_sql("data_lag"), params).fetchall()[0]
    return lag, recent


def pinned(con: psycopg.Connection, city: str) -> dict | None:
    """The methods of the last selection: {variable: {"short": {lead: method}, "long": method}}.
    None unless every variable has them (a first run, or a half-finished selection)."""
    out: dict = {}
    for variable, lead, method in con.execute(_sql("chosen_methods"), {"city": city}).fetchall():
        pin = out.setdefault(variable, {"short": {}, "long": None})
        if lead <= pipeline.SHORT_LEADS:
            pin["short"][lead] = method
        elif pin["long"] is None:  # the selection stores one long-range method for every lead
            pin["long"] = method
    complete = all(
        v in out and out[v]["long"] and len(out[v]["short"]) == pipeline.SHORT_LEADS
        for v in pipeline.VARIABLES
    )
    return out if complete else None


def forecast_only(
    con: psycopg.Connection, city: City, today: date, pin: dict, use_lstm: bool
) -> list[str]:
    """Issue today's forecast with the pinned methods, refitted on the newest data. Nothing is
    evaluated or chosen. Returns one line for every place where the stored method could not be
    used and another was (for example a stored LSTM method on a run without the LSTM)."""
    pairs_all = pipeline.model_pairs(con, city.name)
    now = pd.Timestamp(datetime.now(UTC).replace(tzinfo=None, microsecond=0))
    logs, swapped = [], []
    for var in pipeline.VARIABLES:
        actual = pipeline.daily_series(con, city.name, var)
        pairs = models.add_recent_bias(
            pairs_all[pairs_all.variable == var].drop(columns="variable").reset_index(drop=True)
        )
        chosen = pin[var]
        needs_lstm = use_lstm and chosen["long"] != "decay"
        out = pipeline.build_outlook(
            con, city.name, var, actual, pairs, pd.Timestamp(today), needs_lstm, pin=chosen
        )
        used = out.set_index("lead_days")["method"]
        want = {**chosen["short"], pipeline.SHORT_LEADS + 1: chosen["long"]}
        for lead, method in sorted(want.items()):
            if lead in used.index and used[lead] != method:
                span = f"{lead} days ahead" if lead <= pipeline.SHORT_LEADS else "long range"
                swapped.append(
                    f"{var} {span}: stored method {method} could not be used here, "
                    f"{used[lead]} was used"
                )
        live = out.rename(columns={"raw_forecast_c": "published_c"})
        logs.append(pipeline.log_rows(city.name, "live", var, live, now))
    with con.transaction():  # the forecast and the run stamp move together
        warehouse.load(con, "forecast_log", pd.concat(logs, ignore_index=True))
        con.execute(_sql("stamp_run"), {"city": city.name, "today": today, "run_utc": now})
    return swapped


def _plain(rows: list[dict]) -> list[dict]:
    """JSON-safe rows (dates as text, NaN as null), for the checkpoint and the run log."""

    def cell(v):
        if isinstance(v, float) and v != v:
            return None
        return v.isoformat() if isinstance(v, date) else v

    return [
        {k: cell(v) for k, v in row.items()}
        for row in json.loads(
            json.dumps([{k: cell(v) for k, v in r.items()} for r in rows], default=str)
        )
    ]


class DailyRunner:
    """Runs daily runs and answers the gate. `fetch(con, city, today)` is injectable so tests
    and the fault-injection script can stand in for the weather APIs."""

    def __init__(
        self,
        url: str | None = None,
        fetch: Callable | None = None,
        use_lstm: bool = True,
        data_dir: Path | None = None,
    ) -> None:
        self.url = url or database_url()
        self.fetch = fetch or (
            lambda con, city, today: pipeline.fetch_all(
                con, city, "1995-01-01", "2022-01-01", today
            )
        )
        self.use_lstm = use_lstm
        self.data_dir = data_dir
        self._cities: dict[str, City] = dict(CITIES)
        warehouse.connect(self.url).close()  # migrations
        self.pool = open_pool(self.url)
        try:
            saver = PostgresSaver(self.pool)
            saver.setup()
        except BaseException:
            self.pool.close()
            raise
        self.graph = self._build().compile(checkpointer=saver)

    def close(self) -> None:
        self.pool.close()

    # ---- the run log ----

    def _db(self) -> psycopg.Connection:
        return psycopg.connect(self.url, autocommit=True, row_factory=dict_row)

    def get(self, run_id: str) -> dict | None:
        with self._db() as con:
            return con.execute(_sql("run_get"), {"run_id": run_id}).fetchone()

    def _mark(self, run_id: str, status: str, step: str, mode=None, detail=None, error=None):
        params = {
            "run_id": run_id,
            "status": status,
            "step": step,
            "mode": mode,
            "detail": json.dumps(detail or {}, default=str),
            "error": error,
        }
        with self._db() as con:
            con.execute(_sql("run_update"), params)

    @contextmanager
    def _only_one(self):
        """Hold the daily-run lock. It lives on its own connection, so it is released when
        this block ends or the process dies, whatever else happens."""
        con = psycopg.connect(self.url, autocommit=True)
        try:
            if not con.execute("select pg_try_advisory_lock(%s)", [RUN_LOCK]).fetchall()[0][0]:
                raise Busy("another daily run is in progress; try again when it has finished")
            yield
        finally:
            con.close()

    def _for_today(self, city: str, today: date) -> None:
        """Refuse a day the loaded actuals have already reached."""
        with self._db() as con:
            newest = con.execute(_sql("newest_actual"), {"city": city}).fetchone()["newest"]
        if newest is not None and newest >= today:
            raise ValueError(
                f"{today} is in the past for the data loaded (actuals reach {newest}). A daily "
                "run forecasts from today; a forecast made now for an earlier day would be "
                "logged as if it had been issued then."
            )

    # ---- the graph ----

    def _build(self) -> StateGraph:
        def fetch(state: State) -> dict:
            self._mark(state["run_id"], "running", "fetch")
            with warehouse.connect(self.url) as con:
                self.fetch(con, self._cities[state["city"]], date.fromisoformat(state["today"]))
            return {}

        def check(state: State) -> dict:
            self._mark(state["run_id"], "running", "check")
            city, today = state["city"], date.fromisoformat(state["today"])
            with warehouse.connect(self.url) as con:
                warehouse.build_models(con)
                lag, recent = data_lag(con, city, today)
                if lag is None or lag > MAX_LAG:
                    behind = (
                        "there are no actuals" if lag is None else f"actuals are {lag} days behind"
                    )
                    raise StaleData(f"{behind} (limit {MAX_LAG}); no forecast issued")
                if recent < pipeline.WINDOW:
                    raise StaleData(
                        f"a day is missing among the last {pipeline.WINDOW} days of actuals; "
                        "no forecast issued"
                    )
                rows = _plain(drift(con, city))
                first_run = pinned(con, city) is None
            found = {
                "lag_days": lag,
                "warnings": [f"actuals are {lag} day behind"] if lag > 0 else [],
                "drift": rows,
                "drifted": [r for r in rows if r["drifted"]],
                "mode": "reselect" if first_run else "forecast",
            }
            self._mark(state["run_id"], "running", "check", detail=found)
            return found

        def gate(state: State) -> dict:
            if not state["drifted"] or state["mode"] == "reselect":
                return {}
            decision = state.get("decision")  # given on an earlier attempt of this run
            if decision is None:
                params = {"city": state["city"], "today": state["today"], "days": SNOOZE_DAYS}
                with self._db() as con:
                    last = con.execute(_sql("last_decision"), params).fetchone()
                if last:  # asked and answered within the last SNOOZE_DAYS: do not ask again
                    note = (
                        f"drift still flagged; it was {last['decision']} on {last['today']} "
                        f"and is not asked again for {SNOOZE_DAYS} days"
                    )
                    self._mark(state["run_id"], "running", "gate", detail={"snoozed": note})
                    return {"snoozed": note}
                self._mark(state["run_id"], "waiting_approval", "gate")
                approve = interrupt({"run_id": state["run_id"], "drifted": state["drifted"]})
                decision = "approved" if approve else "declined"
            mode = "reselect" if decision == "approved" else "forecast"
            self._mark(state["run_id"], "running", "gate", detail={"decision": decision})
            return {"decision": decision, "mode": mode}

        def forecast(state: State) -> dict:
            self._mark(state["run_id"], "running", "forecast", mode=state["mode"])
            city, today = self._cities[state["city"]], date.fromisoformat(state["today"])
            with warehouse.connect(self.url) as con:
                if state["mode"] == "reselect":
                    pipeline.run_city(con, city, today, use_lstm=self.use_lstm)
                    swapped = []
                else:
                    swapped = forecast_only(con, city, today, pinned(con, city.name), self.use_lstm)
                if self.data_dir is not None:
                    warehouse.backup(con, self.data_dir)
            return {"warnings": [*state.get("warnings", []), *swapped]}

        def finish(state: State) -> dict:
            detail = {"warnings": state.get("warnings", [])}
            self._mark(state["run_id"], "ok", "done", mode=state["mode"], detail=detail)
            return {}

        g = StateGraph(State)
        for name, node in (
            ("fetch", fetch),
            ("check", check),
            ("gate", gate),
            ("forecast", forecast),
            ("finish", finish),
        ):
            g.add_node(name, node)
        g.add_edge(START, "fetch")
        g.add_edge("fetch", "check")
        g.add_edge("check", "gate")
        g.add_edge("gate", "forecast")
        g.add_edge("forecast", "finish")
        g.add_edge("finish", END)
        return g

    def _go(self, run_id: str, attempt: int, what) -> dict:
        """Run the graph until it ends, waits or fails; the row in app_run_log says which."""
        # one checkpoint thread per attempt: a new attempt starts from the first step
        config = {"configurable": {"thread_id": f"daily:{run_id}:{attempt}"}}
        try:
            self.graph.invoke(what, config, durability="sync")
        except Exception as exc:
            # run_update.sql never changes a row that is ok: if only the save of the last
            # checkpoint failed, the finished run stays finished
            reason = f"{type(exc).__name__}: {str(exc).strip()}"
            self._mark(run_id, "failed", self.get(run_id)["step"], error=reason)
        return self.get(run_id)

    def run(self, city: City, today: date) -> dict:
        """Today's run for a city. A finished run, or one waiting for a decision, is
        returned as it is. A run that failed or was cut off is attempted again from the
        first step: every step is safe to repeat, and the failed step often needs what an
        earlier one fetches (data that was late)."""
        run_id = f"{city.name}-{today.isoformat()}"
        self._cities[city.name] = city
        with self._only_one():
            row = self.get(run_id)
            if row and row["status"] in ("ok", "waiting_approval"):
                return row
            self._for_today(city.name, today)
            params = {"run_id": run_id, "city": city.name, "today": today}
            with self._db() as con:
                con.execute(_sql("run_supersede"), params)  # older runs nobody answered
                attempt = con.execute(_sql("run_start"), params).fetchone()["attempts"]
            start = {"run_id": run_id, "city": city.name, "today": today.isoformat()}
            decided = (row or {}).get("detail", {}).get("decision")
            if decided:  # the answer given before this run failed still stands
                start["decision"] = decided
            return self._go(run_id, attempt, start)

    def decide(self, run_id: str, approve: bool, city: City | None = None) -> dict:
        """Answer a run that is waiting at the gate: approve re-chooses the methods, decline
        forecasts with the current ones. `city` is only needed for a city that is not in the
        configuration and was started by another process."""
        with self._only_one():
            row = self.get(run_id)
            if row is None:
                raise LookupError(f"no such run: {run_id!r}")
            if row["status"] != "waiting_approval":
                raise ValueError(
                    f"run {run_id!r} is not waiting for a decision (it is {row['status']})"
                )
            if city is not None:
                self._cities[city.name] = city
            if row["city"] not in self._cities:
                raise LookupError(f"unknown city {row['city']!r}; pass it to decide()")
            self._for_today(row["city"], row["today"])
            return self._go(run_id, row["attempts"], Command(resume=approve))
