"""Sprint 05: operations. The daily run and its run log, the drift check and the approval gate
before any retraining, what happens on an API outage, late data and a run cut off mid-step,
the scored question set's graders, and trimming of long conversations.

Real Postgres. The daily run uses a small synthetic city (seconds, not minutes) and a fake
fetch step, so no test touches the network.
"""

from datetime import date, timedelta

import pandas as pd
import psycopg
import pytest
from conftest import TEST_URL, fresh_db
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from test_sprint3_review import TODAY, seed_small_city

from weatherwise import ingest, ops, pipeline, warehouse
from weatherwise.agent import evals
from weatherwise.agent.graph import build_agent
from weatherwise.agent.scripted import ScriptedModel
from weatherwise.config import City

CITY = City("t", 0.0, 0.0, "UTC")
NEXT = TODAY + timedelta(days=1)  # the day after the seeded selection run
TABLES = {  # loader name -> query that returns exactly the columns the loader takes
    "actual_daily": "select city, date, tmax_c, tmin_c, precip_mm from raw_actual_daily",
    "published_hourly": "select city, model, ts_local, lead_days, temp_c from raw_published_hourly",
    "live_forecast": "select city, model, issued_on, date, tmax_c, tmin_c, precip_mm "
    "from raw_live_forecast",
    "forecast_log": "select city, kind, issued_on, date, variable, lead_days, pred_c, lo_c, "
    "hi_c, published_c, method, logged_at from log_forecast",
    "model_eval": "select * from app_model_eval",
    "run": "select * from app_run",
}


@pytest.fixture(autouse=True)
def small(monkeypatch):
    """Two leads and a 10-day horizon keep every run short."""
    monkeypatch.setattr(pipeline, "SHORT_LEADS", 2)
    monkeypatch.setattr(pipeline, "HORIZON", 10)


@pytest.fixture(scope="module")
def selected():
    """The seeded city after one full selection run, kept in memory so each test can start
    from it without paying for the selection again."""
    mp = pytest.MonkeyPatch()
    mp.setattr(pipeline, "SHORT_LEADS", 2)
    mp.setattr(pipeline, "HORIZON", 10)
    con = fresh_db()
    seed_small_city(con)
    pipeline.run_city(con, CITY, TODAY, use_lstm=False)
    frames = {name: warehouse.frame(con, sql) for name, sql in TABLES.items()}
    con.close()
    mp.undo()
    return frames


@pytest.fixture
def con(selected):
    c = fresh_db()
    for name, df in selected.items():
        warehouse.load(c, name, df)
    warehouse.build_models(c)
    yield c
    c.close()


def fetch_for(actual_through: date | None = None):
    """A fetch step that loads what the APIs would: a live forecast issued today and, unless
    told otherwise, actuals up to yesterday. Returns (fetch, calls)."""
    calls = []

    def fetch(con, city, today):
        calls.append(today)
        last = con.execute("select max(date) from raw_actual_daily").fetchall()[0][0]
        end = actual_through or today - timedelta(days=1)
        days = pd.date_range(last + timedelta(days=1), end, freq="D")
        if len(days):
            new = pd.DataFrame(
                {"city": city.name, "date": days, "tmax_c": 21.0, "tmin_c": 13.0, "precip_mm": 0.0}
            )
            warehouse.load(con, "actual_daily", new)
        ahead = pd.date_range(today + timedelta(days=1), periods=6, freq="D")
        live = pd.DataFrame(
            {
                "city": city.name,
                "issued_on": pd.Timestamp(today),
                "date": ahead,
                "tmax_c": 24.0,
                "tmin_c": 16.0,
                "precip_mm": 0.0,
            }
        )
        warehouse.load(con, "live_forecast", live)

    return fetch, calls


def runner(fetch):
    return ops.DailyRunner(TEST_URL, fetch=fetch, use_lstm=False)


def live_rows(con, day: date) -> list:
    return con.execute(
        "select variable, lead_days, method, pred_c, published_c from log_forecast "
        "where kind = 'live' and issued_on = %s order by variable, lead_days",
        [day],
    ).fetchall()


def chosen(con) -> list:
    return con.execute(
        "select variable, lead_days, method, test_mae_c from app_model_eval where chosen "
        "order by variable, lead_days"
    ).fetchall()


def make_drift(con) -> None:
    """Make the recent forecasts 3 C worse than the methods were when they were chosen."""
    con.execute(
        "update log_forecast set pred_c = pred_c + 3 where lead_days <= 2 and kind = 'hindcast'"
    )


# ---- the daily run -----------------------------------------------------------------------


def test_daily_run_forecasts_with_the_stored_methods_and_logs_the_run(con):
    """Fails if the daily run re-chooses methods, issues no forecast, or leaves no record."""
    before = chosen(con)
    fetch, calls = fetch_for()
    r = runner(fetch)
    try:
        out = r.run(CITY, NEXT)
    finally:
        r.close()
    assert (out["status"], out["step"], out["mode"], out["attempts"]) == (
        "ok",
        "done",
        "forecast",
        1,
    )
    assert calls == [NEXT] and out["run_id"] == f"t-{NEXT}"
    rows = live_rows(con, NEXT)
    assert len(rows) == 20  # 10 days x high and low
    used = {(v, lead): m for v, lead, m, _, _ in rows}
    assert all(used[(v, lead)] == m for v, lead, m, _ in before)
    assert chosen(con) == before
    assert con.execute("select today, test_start from app_run").fetchall() == [
        (NEXT, date(2024, 12, 31))  # the stamp moves; the selection's test window does not
    ]
    detail = out["detail"]
    assert detail["lag_days"] == 0 and detail["warnings"] == [] and detail["drifted"] == []
    assert [(d["variable"], d["lead_days"]) for d in detail["drift"]] == [
        ("tmax", 1),
        ("tmax", 2),
        ("tmin", 1),
        ("tmin", 2),
    ]


def test_running_again_the_same_day_does_no_work(con):
    """Fails if a second run on the same day fetches again or rewrites the day's forecast."""
    fetch, calls = fetch_for()
    r = runner(fetch)
    try:
        r.run(CITY, NEXT)
        first = con.execute("select max(logged_at) from log_forecast where kind='live'").fetchall()
        again = r.run(CITY, NEXT)
    finally:
        r.close()
    assert (again["status"], again["attempts"]) == ("ok", 1) and calls == [NEXT]
    assert (
        con.execute("select max(logged_at) from log_forecast where kind='live'").fetchall() == first
    )


def test_the_stored_method_is_used_even_where_selection_would_pick_another(con):
    """Fails if the daily run quietly picks its own method. The stored choice for the high
    one day ahead is switched to 'raw' (the published forecast as is); the forecast issued
    must then equal the published value, although a correction is clearly better here."""
    con.execute(
        "update app_model_eval set chosen = (method = 'raw') "
        "where variable = 'tmax' and lead_days = 1"
    )
    fetch, _ = fetch_for()
    r = runner(fetch)
    try:
        r.run(CITY, NEXT)
    finally:
        r.close()
    rows = {(v, lead): (m, pred, pub) for v, lead, m, pred, pub in live_rows(con, NEXT)}
    method, pred, published = rows[("tmax", 1)]
    assert method == "raw" and pred == published == 24.0
    assert rows[("tmax", 2)][0] != "raw" and rows[("tmax", 2)][1] < 23.5  # warm bias removed


def test_first_run_with_no_stored_methods_selects_them_without_asking():
    """Fails if a brand new city waits for an approval nobody can meaningfully give."""
    c = fresh_db()
    seed_small_city(c)
    fetch, _ = fetch_for()
    r = runner(fetch)
    try:
        out = r.run(CITY, TODAY)
    finally:
        r.close()
    assert (out["status"], out["mode"]) == ("ok", "reselect")
    assert len(chosen(c)) == 20 and len(live_rows(c, TODAY)) == 20
    c.close()


# ---- drift and the approval gate ---------------------------------------------------------


def score_rows(con, n_days: int, miss: float, baseline: float, live_miss: float | None = None):
    """n_days of day-ahead highs that were all `miss` C too warm, against a stored `baseline`."""
    c = "t"
    days = pd.date_range("2026-01-01", periods=n_days, freq="D")
    warehouse.load(
        con,
        "actual_daily",
        pd.DataFrame({"city": c, "date": days, "tmax_c": 20.0, "tmin_c": 10.0, "precip_mm": 0.0}),
    )
    rows = []
    for kind, off in (("hindcast", miss), ("live", live_miss)):
        if off is None:
            continue
        for d in days:
            rows.append(
                {
                    "city": c,
                    "kind": kind,
                    "issued_on": d - pd.Timedelta(days=1),
                    "date": d,
                    "variable": "tmax",
                    "lead_days": 1,
                    "pred_c": 20.0 + off,
                    "lo_c": 18.0,
                    "hi_c": 24.0,
                    "published_c": 21.0,
                    "method": "blend",
                    "logged_at": pd.Timestamp("2026-02-01"),
                }
            )
    warehouse.load(con, "forecast_log", pd.DataFrame(rows))
    warehouse.load(
        con,
        "model_eval",
        pd.DataFrame(
            [
                {
                    "city": c,
                    "variable": "tmax",
                    "lead_days": 1,
                    "method": "blend",
                    "cv_mae_c": baseline,
                    "test_mae_c": baseline,
                    "test_days": 300,
                    "chosen": True,
                    "coverage_pct": 80.0,
                }
            ]
        ),
    )
    warehouse.build_models(con)


@pytest.mark.parametrize(
    ("n_days", "miss", "baseline", "drifted"),
    [
        (14, 2.0, 1.0, True),  # twice the stored miss, 1.0 C worse, enough days
        (13, 2.0, 1.0, False),  # one day short
        (14, 2.8, 2.0, False),  # 0.8 C worse, but under 1.5 times
        (14, 1.5, 1.0, False),  # exactly 1.5 times is not "over"
        (14, 0.6, 0.2, False),  # three times, but only 0.4 C worse
        (14, 3.0, 2.0, False),  # 1.0 C worse, but exactly 1.5 times
        (14, 0.75, 0.25, False),  # three times, but exactly 0.5 C worse
        (14, 0.8, 0.25, True),  # just past both
    ],
)
def test_drift_needs_enough_days_a_large_ratio_and_a_real_gap(n_days, miss, baseline, drifted):
    """Fails if any one of the three conditions is dropped or its boundary moves."""
    c = fresh_db()
    score_rows(c, n_days, miss, baseline)
    rows = ops.drift(c, "t")
    c.close()
    assert len(rows) == 1
    assert (rows[0]["n_days"], rows[0]["recent_mae_c"], rows[0]["drifted"]) == (
        n_days,
        miss,
        drifted,
    )


def test_drift_uses_the_last_30_days_and_prefers_what_was_issued_live():
    """Fails if old misses dilute the check, or a replay hides what was really issued."""
    c = fresh_db()
    score_rows(c, 40, 3.0, 1.0, live_miss=0.5)  # replays say 3.0 off, the live ones were 0.5 off
    row = ops.drift(c, "t")[0]
    assert (row["n_days"], row["n_live"], row["recent_mae_c"], row["drifted"]) == (
        30,
        30,
        0.5,
        False,
    )
    assert row["first_day"] == date(2026, 1, 11) and row["last_day"] == date(2026, 2, 9)
    c.close()


def test_drift_pauses_the_run_and_declining_keeps_the_methods(con):
    """Fails if drift leads to a retrain, or to a forecast, before anyone has decided."""
    make_drift(con)
    before = chosen(con)
    fetch, _ = fetch_for()
    r = runner(fetch)
    try:
        out = r.run(CITY, NEXT)
        assert (out["status"], out["step"]) == ("waiting_approval", "gate")
        assert {(d["variable"], d["lead_days"]) for d in out["detail"]["drifted"]} == {
            ("tmax", 1),
            ("tmax", 2),
            ("tmin", 1),
            ("tmin", 2),
        }
        assert live_rows(con, NEXT) == [] and chosen(con) == before
        assert r.run(CITY, NEXT)["status"] == "waiting_approval"  # asking again does not decide
        done = r.decide(out["run_id"], approve=False)
    finally:
        r.close()
    assert (done["status"], done["mode"], done["detail"]["decision"]) == (
        "ok",
        "forecast",
        "declined",
    )
    assert len(live_rows(con, NEXT)) == 20 and chosen(con) == before


def test_approving_drift_reselects_the_methods(con):
    """Fails if an approval does not lead to a new selection on today's data."""
    make_drift(con)
    fetch, _ = fetch_for()
    r = runner(fetch)
    try:
        out = r.run(CITY, NEXT)
        done = r.decide(out["run_id"], approve=True)
        with pytest.raises(LookupError):
            r.decide("t-1999-01-01", approve=True)
        with pytest.raises(ValueError, match="not waiting"):
            r.decide(out["run_id"], approve=True)
    finally:
        r.close()
    assert (done["status"], done["mode"], done["detail"]["decision"]) == (
        "ok",
        "reselect",
        "approved",
    )
    after = ops.drift(con, "t")  # the replays were made again with the new methods
    assert len(after) == 4 and not any(d["drifted"] for d in after)
    assert len(live_rows(con, NEXT)) == 20
    assert con.execute("select today, test_start from app_run").fetchall() == [
        (NEXT, date(2025, 1, 1))
    ]


# ---- faults ------------------------------------------------------------------------------


def test_an_api_outage_fails_the_run_at_fetch_and_a_rerun_recovers(con):
    """Fails if an outage leaves a half-made forecast, loses its reason, or blocks the retry."""

    def down(con, city, today):
        raise ingest.IngestError("503 from the archive after 4 tries")

    sums = warehouse.checksum(con)
    r = runner(down)
    try:
        out = r.run(CITY, NEXT)
    finally:
        r.close()
    assert (out["status"], out["step"]) == ("failed", "fetch")
    assert out["error"] == "IngestError: 503 from the archive after 4 tries"
    assert live_rows(con, NEXT) == [] and warehouse.checksum(con) == sums
    fetch, calls = fetch_for()
    r = runner(fetch)
    try:
        again = r.run(CITY, NEXT)
    finally:
        r.close()
    assert (again["status"], again["attempts"], again["error"]) == ("ok", 2, None)
    assert calls == [NEXT] and len(live_rows(con, NEXT)) == 20


def test_late_actuals_are_a_warning_then_a_stop(con):
    """Fails if a forecast is issued from data the models call too old, or lateness goes
    unsaid. The models need an observation at most 2 days old. The seeded actuals end the
    day before TODAY and the fake fetch brings none."""
    end = TODAY - timedelta(days=1)
    fetch, _ = fetch_for(actual_through=end)
    r = runner(fetch)
    try:
        late = r.run(CITY, TODAY + timedelta(days=1))  # newest actual is 2 days old
        stale = r.run(CITY, TODAY + timedelta(days=2))  # 3 days old
    finally:
        r.close()
    assert late["status"] == "ok" and late["detail"]["lag_days"] == 1
    assert late["detail"]["warnings"] == ["actuals are 1 day behind"]
    assert len(live_rows(con, TODAY + timedelta(days=1))) == 20
    assert (stale["status"], stale["step"]) == ("failed", "check")
    assert stale["error"] == "StaleData: actuals are 2 days behind (limit 1); no forecast issued"
    assert live_rows(con, TODAY + timedelta(days=2)) == []


class Crash(BaseException):
    """Stands in for the process dying mid-step."""


def test_a_run_cut_off_mid_step_is_marked_running_and_a_rerun_completes_it(con):
    """Fails if a killed run looks finished, or cannot be run again."""
    good, calls = fetch_for()
    state = {"crash": True}

    def dies_after_loading(con, city, today):
        good(con, city, today)
        if state["crash"]:
            state["crash"] = False
            raise Crash()

    r = runner(dies_after_loading)
    with pytest.raises(Crash):
        r.run(CITY, NEXT)
    r.close()
    row = con.execute("select status, step, attempts from app_run_log").fetchall()
    assert row == [("running", "fetch", 1)] and live_rows(con, NEXT) == []
    r = runner(dies_after_loading)
    try:
        out = r.run(CITY, NEXT)
    finally:
        r.close()
    assert (out["status"], out["attempts"]) == ("ok", 2) and calls == [NEXT, NEXT]
    assert len(live_rows(con, NEXT)) == 20


# ---- the question set's graders ----------------------------------------------------------


def answer(text, grounded=True, error=None, tools=()):
    return {
        "answer": text,
        "grounded": grounded,
        "error": error,
        "tool_calls": [{"tool": t, "status": "ok"} for t in tools],
    }


def test_grader_wants_every_expected_number_and_a_checked_answer():
    """Fails if a wrong, missing, refused or failed answer scores as a pass."""
    case = {"expect": [70.3, 2.2]}
    assert evals.grade(case, answer("High 70.3 F; day-ahead miss 2.2 F."))["passed"] is True
    missing = evals.grade(case, answer("High 70.3 F."))
    assert missing["passed"] is False and "2.2" in missing["why"]
    assert evals.grade(case, answer("High 70.31 F, miss 2.2 F."))["passed"] is False
    assert evals.grade(case, answer("High 70.3 F, miss 2.2 F.", grounded=False))["passed"] is False
    assert evals.grade(case, answer("70.3 and 2.2", error="model unavailable"))["passed"] is False
    assert evals.grade({"expect": [1756]}, answer("Based on 1,756 days."))["passed"] is True


def test_grader_checks_which_number_is_which_and_which_day():
    """Fails if two right numbers stated the wrong way round, or the right value on the wrong
    day, score as a pass."""
    case = {
        "expect": [
            {"value": 73.0, "label": "published"},
            {"value": 72.1, "label": "weatherwise"},
        ]
    }
    right = "The published forecast says 73.0 F. Weatherwise says 72.1 F."
    swapped = "The published forecast says 72.1 F. Weatherwise says 73.0 F."
    assert evals.grade(case, answer(right))["passed"] is True
    wrong = evals.grade(case, answer(swapped))
    assert wrong["passed"] is False and wrong["why"] == "73.0 is not stated as published"
    day = {"expect": [{"value": 72.1, "label": None}, {"value": "Sunday", "label": None}]}
    assert evals.grade(day, answer("The warmest is sunday at 72.1 F."))["passed"] is True
    assert evals.grade(day, answer("The warmest is Monday at 72.1 F."))["why"] == "missing Sunday"


def test_grader_checks_tools_declines_and_answers_that_must_hold_no_figure():
    """Fails if 'no data' questions pass with an invented figure, a guess passes where a
    decline is required, or tool use is not checked."""
    used = {"expect": [], "tool": "get_scoreboard"}
    assert evals.grade(used, answer("No readings yet.", tools=["get_scoreboard"]))["passed"] is True
    assert evals.grade(used, answer("No readings yet.", tools=["get_outlook"]))["passed"] is False
    none = {"expect": [], "no_figures": True}
    assert evals.grade(none, answer("The outlook stops on 2026-12-14."))["passed"] is True
    asked = {**none, "asked": "Estimate the high 45 days from now."}
    assert evals.grade(asked, answer("I have nothing 45 days out."))["passed"] is True
    assert evals.grade(asked, answer("About 61 F in 45 days."))["passed"] is False
    bad = evals.grade(none, answer("Probably about 61 F on Dec 25."))
    assert bad["passed"] is False and "61" in bad["why"]
    declines = {"expect": [], "declines": True}
    said_no = "I can’t give a high for that day. The last stored day is at 65.8 F."
    assert evals.grade(declines, answer(said_no))["passed"] is True
    assert (
        evals.grade(declines, answer("It will be 65.8 F, well past the average."))["passed"]
        is False
    )
    withheld = evals.grade(declines, answer("I cannot give that answer.", grounded=False))
    assert withheld == {"passed": True, "why": "ok: withheld by the number check"}
    banned = {"expect": [], "must_not_contain": ["391"]}
    assert evals.grade(banned, answer("That is 391."))["passed"] is False
    assert evals.grade(banned, answer("That is 391.5."))["passed"] is True  # another number
    assert evals.grade(banned, answer("Ticket 3910 is unrelated."))["passed"] is True
    assert evals.grade(banned, answer("I only answer weather questions."))["passed"] is True


def test_expected_values_are_read_from_the_database_and_rounded_like_the_tools(con):
    """Fails if the answer key is typed in by hand, converts a gap like a temperature, rounds
    after converting, or rounds half-to-even where Postgres rounds half up.
    20.05 C: rounded first it is 20.1 C = 68.2 F; converted first it would be 68.1 F.
    1.145: half up gives 1.15 (Python's round gives 1.14)."""
    case = {
        "sql": "select 21.26 as a, 2.5 as b, count(*) as n, 20.05 as c, 1.145 as d, "
        "'Sunday   ' as w from app_run",
        "expect": [
            {"column": "a", "as": "temp_f"},
            {"column": "b", "as": "gap_f"},
            {"column": "n", "as": "value"},
            {"column": "c", "as": "temp_f"},
            {"column": "d", "as": "value", "round": 2},
            {"column": "d", "as": "gap_f", "round": 2},
            {"column": "w", "as": "text", "label": "warmest"},
        ],
    }
    got = evals.expected(con, case, {})
    assert [g["value"] for g in got] == [70.3, 4.5, 1, 68.2, 1.15, 2.1, "Sunday"]
    assert got[-1]["label"] == "warmest" and got[0]["label"] is None
    filled = evals.fill("High on {day}?", con, "select date '2026-01-02' as day", {})
    assert filled == ("High on 2026-01-02?", {"day": "2026-01-02"})
    with pytest.raises(LookupError, match="no row"):
        evals.expected(con, {"sql": "select 1 as a where false", "expect": []}, {})


# ---- long conversations ------------------------------------------------------------------


def test_only_recent_questions_are_sent_to_the_model_but_none_are_forgotten(con, monkeypatch):
    """Fails if a long conversation grows without limit on its way to the model, starts in
    the middle of a turn, or loses its earlier turns from the saved history."""
    monkeypatch.setattr("weatherwise.agent.graph.KEEP_QUESTIONS", 2)
    sent = []

    def reply(messages):
        sent.append(messages)
        return AIMessage(content="Noted.")

    agent = build_agent(TEST_URL, model=ScriptedModel(responses=[reply] * 4), today=TODAY)
    try:
        for n in range(1, 5):
            agent.ask(f"question number-{n}", thread_id="th1")
        saved = agent.history("th1")
    finally:
        agent.close()
    last = sent[-1]
    assert isinstance(last[0], SystemMessage) and isinstance(last[1], HumanMessage)
    asked = [m.content for m in last if isinstance(m, HumanMessage)]
    assert asked == ["question number-3", "question number-4"]
    assert "2 earlier questions are not shown" in last[0].content
    assert [m["content"] for m in saved if m["role"] == "user"] == [
        f"question number-{n}" for n in range(1, 5)
    ]


def test_a_finished_run_stays_ok_when_only_the_last_save_fails(con, monkeypatch):
    """Fails if a run whose forecast is issued and which is marked ok is flipped to failed
    by an error that comes after it (seen when the database restarted while the last
    checkpoint was being saved; here the error is raised right after the row is marked
    ok)."""
    fetch, _ = fetch_for()
    r = runner(fetch)
    real = r._mark

    def mark_then_break(run_id, status, step, **kw):
        real(run_id, status, step, **kw)
        if status == "ok":
            raise RuntimeError("connection lost while saving the last checkpoint")

    monkeypatch.setattr(r, "_mark", mark_then_break)
    try:
        out = r.run(CITY, NEXT)
    finally:
        r.close()
    assert (out["status"], out["step"], out["error"]) == ("ok", "done", None)
    assert len(live_rows(con, NEXT)) == 20


# ---- added after the sprint-05 reviews ---------------------------------------------------


def test_only_one_daily_run_at_a_time(con):
    """Fails if a second run can start while another holds the lock (two runs would rebuild
    the tables under each other and both count as attempts)."""
    fetch, calls = fetch_for()
    r = runner(fetch)
    holder = psycopg.connect(TEST_URL, autocommit=True)
    holder.execute("select pg_advisory_lock(%s)", [ops.RUN_LOCK])
    try:
        with pytest.raises(ops.Busy):
            r.run(CITY, NEXT)
        assert calls == [] and con.execute("select count(*) from app_run_log").fetchall() == [(0,)]
        holder.close()  # the other run ends (or dies): the lock goes with its connection
        assert r.run(CITY, NEXT)["status"] == "ok"
    finally:
        holder.close()
        r.close()


def test_a_day_the_data_has_already_reached_is_refused(con):
    """Fails if a run for a past day is accepted: its forecast would be made with data from
    after that day and logged as if it had been issued then, and it could never be fixed."""
    fetch, calls = fetch_for()
    r = runner(fetch)
    try:
        with pytest.raises(ValueError, match="in the past for the data loaded"):
            r.run(CITY, TODAY - timedelta(days=5))
    finally:
        r.close()
    assert calls == [] and con.execute("select count(*) from app_run_log").fetchall() == [(0,)]


def test_an_unanswered_run_is_closed_when_the_next_day_starts(con):
    """Fails if yesterday's waiting run can still be approved today: it would forecast for
    yesterday using today's data."""
    make_drift(con)
    fetch, _ = fetch_for()
    r = runner(fetch)
    try:
        first = r.run(CITY, NEXT)
        second = r.run(CITY, NEXT + timedelta(days=1))
        old = r.get(first["run_id"])
        with pytest.raises(ValueError, match="not waiting"):
            r.decide(first["run_id"], approve=True)
    finally:
        r.close()
    assert first["status"] == "waiting_approval" and second["status"] == "waiting_approval"
    assert (old["status"], old["error"]) == (
        "failed",
        f"no decision was given; superseded by {second['run_id']}",
    )
    assert live_rows(con, NEXT) == []


def test_an_approval_survives_a_failure_after_the_gate(con, monkeypatch):
    """Fails if a run that was approved and then failed asks for the approval again, or
    forgets it and forecasts without re-choosing."""
    make_drift(con)
    real = pipeline.run_city
    state = {"fail": True}

    def fails_once(*args, **kw):
        if state["fail"]:
            state["fail"] = False
            raise RuntimeError("out of memory while choosing methods")
        return real(*args, **kw)

    monkeypatch.setattr(pipeline, "run_city", fails_once)
    fetch, _ = fetch_for()
    r = runner(fetch)
    try:
        waiting = r.run(CITY, NEXT)
        failed = r.decide(waiting["run_id"], approve=True)
        again = r.run(CITY, NEXT)
    finally:
        r.close()
    assert (failed["status"], failed["step"]) == ("failed", "forecast")
    assert failed["error"] == "RuntimeError: out of memory while choosing methods"
    assert (again["status"], again["mode"], again["attempts"]) == ("ok", "reselect", 2)
    assert again["detail"]["decision"] == "approved" and len(live_rows(con, NEXT)) == 20


def test_after_a_decision_the_gate_does_not_ask_again_for_a_week(con):
    """Fails if a declined drift flag stops the run again the very next day, or if the
    silence lasts forever."""
    make_drift(con)
    fetch, _ = fetch_for()
    r = runner(fetch)
    try:
        first = r.run(CITY, NEXT)
        r.decide(first["run_id"], approve=False)
        next_day = r.run(CITY, NEXT + timedelta(days=1))
        con.execute("update app_run_log set today = today - 8, run_id = run_id || '-old'")
        later = r.run(CITY, NEXT + timedelta(days=2))
    finally:
        r.close()
    assert (next_day["status"], next_day["mode"]) == ("ok", "forecast")
    assert len(next_day["detail"]["drifted"]) == 4 and "decision" not in next_day["detail"]
    assert next_day["detail"]["snoozed"] == (
        f"drift still flagged; it was declined on {NEXT} and is not asked again for 7 days"
    )
    assert later["status"] == "waiting_approval"  # the last decision is now 9 and 10 days old


def test_a_new_attempt_starts_with_a_clean_record(con):
    """Fails if a rerun keeps the failed attempt's warnings or mode on its row."""
    end = TODAY - timedelta(days=1)
    late, _ = fetch_for(actual_through=end)
    day = TODAY + timedelta(days=2)
    r = runner(late)
    try:
        failed = r.run(CITY, day)
    finally:
        r.close()
    con.execute(
        'update app_run_log set detail = detail || \'{"warnings": ["left over"], "old": 1}\', '
        "mode = 'reselect' where run_id = %s",
        [failed["run_id"]],
    )
    good, _ = fetch_for()
    r = runner(good)
    try:
        again = r.run(CITY, day)
    finally:
        r.close()
    assert failed["status"] == "failed" and (again["status"], again["attempts"]) == ("ok", 2)
    assert (again["mode"], again["detail"]["warnings"], again["error"]) == ("forecast", [], None)
    assert "old" not in again["detail"]  # a key no later step writes: only the reset removes it


def test_a_decision_survives_an_attempt_that_fails_before_the_gate(con, monkeypatch):
    """Fails if the decision is wiped from the row when a new attempt starts: an attempt
    that dies before the gate would leave no trace of it, and the one after would ask
    again. Approved, fails while choosing methods; next attempt fails at the fetch; the
    third must finish without asking."""
    make_drift(con)
    real = pipeline.run_city
    left = {"forecast": 1, "fetches": 0}

    def fails_once(*args, **kw):
        if left["forecast"]:
            left["forecast"] = 0
            raise RuntimeError("out of memory while choosing methods")
        return real(*args, **kw)

    monkeypatch.setattr(pipeline, "run_city", fails_once)
    good, _ = fetch_for()

    def fetch(db, city, today):
        left["fetches"] += 1
        if left["fetches"] == 2:
            raise RuntimeError("weather API down")
        good(db, city, today)

    r = runner(fetch)
    try:
        waiting = r.run(CITY, NEXT)
        r.decide(waiting["run_id"], approve=True)
        second = r.run(CITY, NEXT)
        third = r.run(CITY, NEXT)
    finally:
        r.close()
    assert (second["status"], second["error"]) == ("failed", "RuntimeError: weather API down")
    assert second["detail"].get("decision") == "approved"
    assert (third["status"], third["mode"], third["attempts"]) == ("ok", "reselect", 3)
    assert third["detail"]["decision"] == "approved" and len(live_rows(con, NEXT)) == 20


def test_a_hole_in_the_last_three_days_stops_the_run_at_the_check(con):
    """Fails if a missing day among the newest actuals is only found later, inside the
    forecast step, after everything else has run."""
    hole = TODAY - timedelta(days=2)
    con.execute("update raw_actual_daily set tmax_c = null where date = %s", [hole])
    fetch, _ = fetch_for()
    r = runner(fetch)
    try:
        out = r.run(CITY, NEXT)
    finally:
        r.close()
    assert (out["status"], out["step"]) == ("failed", "check")
    assert out["error"] == (
        "StaleData: a day is missing among the last 3 days of actuals; no forecast issued"
    )
    assert live_rows(con, NEXT) == []


def test_a_stored_method_that_cannot_be_used_is_reported_not_swapped_silently(con):
    """Fails if the daily run uses another method than the stored one without saying so.
    The stored long-range method is renamed to 'lstm'; this run has no LSTM, so it falls back
    to decay and must say so."""
    con.execute("update app_model_eval set method = 'lstm' where chosen and lead_days > 2")
    fetch, _ = fetch_for()
    r = runner(fetch)
    try:
        out = r.run(CITY, NEXT)
    finally:
        r.close()
    assert out["status"] == "ok" and out["detail"]["warnings"] == [
        "tmax long range: stored method lstm could not be used here, decay was used",
        "tmin long range: stored method lstm could not be used here, decay was used",
    ]
    long_methods = {m for _, lead, m, _, _ in live_rows(con, NEXT) if lead > 2}
    assert long_methods == {"decay"}


def test_stored_methods_count_only_when_every_variable_has_them(con):
    """Fails if a half-finished selection (one variable missing) is forecast from: the
    missing variable would be chosen afresh by the daily run without anyone deciding."""
    whole = ops.pinned(con, "t")
    assert whole["tmax"] == {"short": {1: "linear", 2: "linear"}, "long": "decay"}
    con.execute("delete from app_model_eval where variable = 'tmin' and lead_days = 2")
    assert ops.pinned(con, "t") is None
    con.execute("delete from app_model_eval")
    assert ops.pinned(con, "t") is None


def test_a_pinned_long_range_method_is_kept_over_the_one_validation_prefers(monkeypatch):
    """Fails if the long-range pin is ignored. Two stand-in backtests: 'decay' misses by 1,
    'lstm' by 3. Unpinned, decay wins; pinned to lstm, lstm is used with its own misses."""
    days = pd.date_range("2024-01-01", periods=800, freq="D")
    series = pd.Series(20.0, index=days)

    def backtest(off):
        rows = [
            {"date": d, "lead_days": lead, "actual_c": 20.0, "pred_c": 20.0 + off}
            for d in days[-40:]
            for lead in range(1, pipeline.HORIZON + 1)
        ]
        return pd.DataFrame(rows)

    both = {"decay": backtest(1.0), "lstm": backtest(3.0)}
    monkeypatch.setattr(pipeline, "long_backtests", lambda *a, **k: (both, None))
    assert pipeline.select_long(series, False)[0] == "decay"
    chosen, resid, _, _ = pipeline.select_long(series, False, "lstm")
    assert chosen == "lstm" and float(resid[5].iloc[0]) == -3.0
    assert pipeline.select_long(series, False, "mix")[0] == "decay"  # not run here: fall back


def test_history_is_cut_at_a_question_and_keeps_tool_results_with_their_question():
    """Fails if trimming starts in the middle of a turn, counts the number check's own note
    as a question, or separates a tool result from the question that caused it."""
    from langchain_core.messages import ToolMessage

    from weatherwise.agent.graph import recent
    from weatherwise.agent.scripted import call

    note = HumanMessage(content="[number check] rewrite", additional_kwargs={"internal": True})
    messages = [
        HumanMessage(content="q1"),
        call("get_outlook", {"city": "t"}, "c1", ai=True),
        ToolMessage(content="{}", tool_call_id="c1"),
        AIMessage(content="a1"),
        HumanMessage(content="q2"),
        note,
        AIMessage(content="a2"),
        HumanMessage(content="q3"),
    ]
    kept, dropped = recent(messages, 2)
    assert dropped == 1 and [m.content for m in kept] == [
        "q2",
        "[number check] rewrite",
        "a2",
        "q3",
    ]
    assert recent(messages, 3) == (messages, 0) and recent(messages, 1)[0] == messages[-1:]


def test_a_figure_from_a_turn_that_was_trimmed_away_is_no_longer_a_source(con, monkeypatch):
    """Fails if the number check accepts a figure the model can no longer see: the check and
    the model must look at the same part of the conversation. With one question kept, the
    reading given in the first question is gone by the second."""
    monkeypatch.setattr("weatherwise.agent.graph.KEEP_QUESTIONS", 1)

    def reply(messages):
        first = any("thermometer" in str(m.content) for m in messages)
        return AIMessage(content="Noted." if first else "Earlier you mentioned 61.5 degrees.")

    agent = build_agent(TEST_URL, model=ScriptedModel(responses=[reply, reply]), today=TODAY)
    try:
        kept = agent.ask("My thermometer said 61.5 this morning. Repeat it.", thread_id="th0")
        agent.ask("My thermometer said 61.5 this morning.", thread_id="th1")
        out = agent.ask("What did I tell you?", thread_id="th1")
    finally:
        agent.close()
    assert kept["grounded"] is True  # while the question is in view, its number is a source
    assert out["grounded"] is False and out["unsupported"] == ["61.5"]
