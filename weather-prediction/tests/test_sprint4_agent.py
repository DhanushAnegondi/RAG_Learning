"""Sprint 04: the LangGraph planning assistant. Real Postgres, a scripted offline model.

Covers the read-only tool layer (role, typed arguments, timeout, retry, log, replay), the number
check on answers, the graph (tools, rewrite, refusal, cost cap, model failure), checkpoints,
preferences across threads, resume after a crash, and the site endpoints.
"""

import json
import os
import re
from datetime import date

import pandas as pd
import psycopg
import pytest
from conftest import TEST_URL, fresh_db
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from test_sprint2_data import actual, hourly

from weatherwise import config, site, warehouse
from weatherwise.agent import grounding, tools
from weatherwise.agent.graph import build_agent
from weatherwise.agent.scripted import ScriptedModel, call

TODAY = date(2026, 11, 14)


def log_row(kind, issued, day, lead, variable, pred, published) -> dict:
    return {
        "city": "t",
        "kind": kind,
        "issued_on": pd.Timestamp(issued),
        "date": pd.Timestamp(day),
        "variable": variable,
        "lead_days": lead,
        "pred_c": pred,
        "lo_c": pred - 1.5,
        "hi_c": pred + 2.5,
        "published_c": published,
        "method": "blend",
        "logged_at": pd.Timestamp("2026-11-14 08:00"),
    }


def seed(con) -> None:
    """Four days of actuals and day-ahead published forecasts, a live outlook issued on the
    14th, one replayed forecast for the 13th, and the user's reading for the 13th."""
    days = ["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]
    warehouse.load(con, "actual_daily", actual("t", [(d, 20.0, 10.0) for d in days]))
    for d, top in zip(days, (21.0, 22.0, 23.0, 16.0), strict=True):  # misses: +1 +2 +3 -4
        temps = [10.0] * 23 + [top]
        warehouse.load(con, "published_hourly", hourly("t", d, 1, temps))
    rows = [
        log_row("live", "2026-11-13", "2026-11-14", 1, "tmax", 30.0, 31.0),  # an older outlook
        log_row("live", "2026-11-14", "2026-11-15", 1, "tmax", 21.26, 22.8),
        log_row("live", "2026-11-14", "2026-11-15", 1, "tmin", 12.04, 13.0),
        log_row("live", "2026-11-14", "2026-11-16", 2, "tmax", 20.0, 19.5),
        log_row("live", "2026-11-14", "2026-11-16", 2, "tmin", 11.0, 12.5),
        log_row("hindcast", "2026-11-12", "2026-11-13", 1, "tmax", 23.0, 24.0),
        log_row("live", "2026-11-14", "2026-11-22", 8, "tmax", 19.0, None),  # no published
        log_row("hindcast", "2026-11-14", "2026-11-15", 1, "tmax", 40.0, 41.0),  # a replay
    ]
    warehouse.load(con, "forecast_log", pd.DataFrame(rows))
    obs = pd.DataFrame(
        [
            {
                "city": "t",
                "date": pd.Timestamp("2026-11-13"),
                "tmax_c": 25.0,
                "tmin_c": None,
                "note": None,
                "entered_at": pd.Timestamp("2026-11-14 09:00"),
            }
        ]
    )
    warehouse.load(con, "user_observation", obs)
    evals = pd.DataFrame(
        [
            {
                "city": "t",
                "variable": "tmax",
                "lead_days": 1,
                "method": "blend",
                "cv_mae_c": 1.0,
                "test_mae_c": 1.5,
                "test_days": 300,
                "chosen": True,
                "coverage_pct": 77.5,
            }
        ]
    )
    warehouse.load(con, "model_eval", evals)
    warehouse.build_models(con)


@pytest.fixture
def con():
    c = fresh_db()
    seed(c)
    yield c
    c.close()


def make(responses, **kw):
    return build_agent(TEST_URL, model=ScriptedModel(responses=responses), today=TODAY, **kw)


@pytest.fixture
def ctx(con):
    agent = make([])
    yield agent.context("local")
    agent.close()


def logged(con, columns="tool, status, attempts"):
    return con.execute(f"select {columns} from agent.tool_call order by started_at").fetchall()


# ---- the read-only role ----------------------------------------------------------------


def test_tools_read_as_a_role_that_cannot_write_or_see_raw_tables(ctx):
    """Fails if a tool query can change data or read tables it was not granted."""
    assert ctx.read("select count(*) as n from log_forecast") == [{"n": 8}]
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):  # read-only before the grant check
        ctx.read("delete from log_forecast")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        ctx.read("select * from raw_actual_daily")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        ctx.read(
            "insert into agent.tool_call (call_id, thread_id, tool, args, status) "
            "values ('x', 'x', 'x', '{}', 'ok')"
        )
    with ctx.pool.connection() as plain:  # the role does not stick to the pooled connection
        assert plain.execute("select current_user as who").fetchall() == [{"who": "weatherwise"}]


def test_marts_stay_readable_after_a_rebuild(con, ctx):
    """Fails if rebuilding the marts (which drops them) leaves the assistant locked out."""
    warehouse.build_models(con)
    assert ctx.read("select count(*) as n from mart_error_by_lead where city = 't'") == [{"n": 2}]


# ---- tools: results, units, arguments ---------------------------------------------------


def test_outlook_tool_returns_the_newest_live_forecast_in_both_units(con, ctx):
    """Fails if an older outlook leaks in, days are not limited, or Fahrenheit is wrong.
    21.26 C rounds to 21.3 C = 70.3 F; the range ends are 19.8 and 23.8 C."""
    out = tools.run_tool(ctx, "th1", call("get_outlook", {"city": "T", "days": 1}, "c1"))
    assert out["status"] == "ok" and out["row_count"] == 1
    row = out["rows"][0]
    assert row["date"] == "2026-11-15" and row["issued_on"] == "2026-11-14"
    assert (row["high_c"], row["high_f"]) == (21.3, 70.3)
    assert (row["high_low_end_c"], row["high_high_end_c"]) == (19.8, 23.8)
    assert (row["low_c"], row["low_f"]) == (12.0, 53.6)
    assert (row["published_high_c"], row["published_high_f"]) == (22.8, 73.0)
    assert (row["low_low_end_c"], row["low_low_end_f"]) == (10.5, 50.9)
    assert (row["low_high_end_c"], row["low_high_end_f"]) == (14.5, 58.1)
    assert (row["published_low_c"], row["published_low_f"]) == (13.0, 55.4)
    assert row["weekday"] == "Sunday" and out["facts"][0].startswith("The likely range aims")


def test_a_day_with_no_published_forecast_has_no_invented_fahrenheit(con, ctx):
    """Fails if a missing value crashes the unit conversion or turns into a number. Day 8
    has a high but no published forecast and no low."""
    out = tools.run_tool(ctx, "th1", call("get_outlook", {"city": "t", "days": 8}, "c1"))
    assert out["status"] == "ok" and out["row_count"] == 3
    far = out["rows"][-1]
    assert (far["lead_days"], far["high_c"], far["high_f"]) == (8, 19.0, 66.2)
    assert far["published_high_c"] is None and "published_high_f" not in far
    assert far["low_c"] is None and "low_f" not in far


def test_error_tool_converts_misses_as_differences_not_temperatures(con, ctx):
    """Fails if a 2.5 C miss is shown as 36.5 F (a temperature) instead of 4.5 F (a gap), or
    if the sign of the bias is lost. Published errors on the four seeded days are +1, +2, +3
    and -4 C: average miss 2.5, bias +0.5, worst 4, two of four days off by 3 or more."""
    args = {"city": "t", "variable": "tmax"}
    out = tools.run_tool(ctx, "th1", call("get_forecast_error_by_lead", args, "c1"))
    row = out["rows"][0]
    assert (row["lead_days"], row["n_days"]) == (1, 4)
    assert (row["published_avg_miss_c"], row["published_avg_miss_f"]) == (2.5, 4.5)
    assert (row["published_worst_miss_c"], row["published_worst_miss_f"]) == (4.0, 7.2)
    assert (row["published_bias_c"], row["published_bias_f"]) == (0.5, 0.9)
    assert row["weatherwise_avg_miss_last_12_months_f"] == 2.7
    assert any("3 C" in f for f in out["facts"]) and any("12 months" in f for f in out["facts"])
    assert row["published_pct_days_off_3c_or_more"] == 50.0
    assert row["weatherwise_avg_miss_last_12_months_c"] == 1.5
    assert row["weatherwise_pct_days_inside_range"] == 77.5


def test_check_day_scoreboard_and_health_tools_read_their_marts(con, ctx):
    """Fails if a tool reads the wrong mart or drops the user's reading."""
    day = tools.run_tool(ctx, "th1", call("check_day", {"city": "t", "day": "2026-11-13"}, "c1"))
    assert day["row_count"] == 1
    row = day["rows"][0]
    assert (row["observed_c"], row["weatherwise_c"], row["weatherwise_error_c"]) == (25.0, 23, -2)
    assert row["inside_range"] is True and row["kind"] == "hindcast"
    assert (row["observed_f"], row["weatherwise_f"]) == (77.0, 73.4)
    assert (row["weatherwise_error_f"], row["published_error_c"]) == (-3.6, -1.0)
    assert row["published_error_f"] == -1.8
    board = tools.run_tool(ctx, "th1", call("get_scoreboard", {"city": "t"}, "c2"))
    score = board["rows"][0]
    assert score["n_checks"] == 1 and score["weatherwise_avg_miss_c"] == 2.0
    assert (score["weatherwise_avg_miss_f"], score["published_avg_miss_f"]) == (3.6, 1.8)
    assert (score["reading_minus_grid_c"], score["reading_minus_grid_f"]) == (5.0, 9.0)
    health = tools.run_tool(ctx, "th1", call("get_data_health", {"city": "t"}, "c3"))
    assert "actuals (ERA5 daily)" in {r["source"] for r in health["rows"]}
    assert health["rows"][0]["usable_days"] == 4
    empty = tools.run_tool(ctx, "th1", call("check_day", {"city": "t", "day": "2020-01-01"}, "c4"))
    assert empty["status"] == "ok" and empty["row_count"] == 0 and "no rows" in empty["note"]


@pytest.mark.parametrize(
    ("name", "args", "why"),
    [
        ("get_outlook", {"city": "t", "days": 31}, "days"),
        ("get_outlook", {"city": "t", "days": 0}, "days"),
        ("get_outlook", {"city": "x" * 41, "days": 1}, "city"),
        ("get_forecast_error_by_lead", {"city": "t", "variable": "wind"}, "variable"),
        ("check_day", {"city": "t", "day": "yesterday"}, "day"),
        ("get_outlook", {"city": "t", "sql": "drop table log_forecast"}, "sql: Extra inputs"),
        ("run_sql", {"query": "select 1"}, "unknown tool 'run_sql'"),
        ("remember_preference", {"key": "units", "value": "kelvin"}, "units must be C or F"),
        ("remember_preference", {"key": "home_city", "value": "atlantis"}, "home_city must be"),
        ("remember_preference", {"key": "hot_day_threshold", "value": "warm"}, "a number and"),
        ("remember_preference", {"key": "hot_day_threshold", "value": "200 F"}, "between -60"),
    ],
)
def test_bad_tool_arguments_are_refused_and_logged_without_running(con, ctx, name, args, why):
    """Fails if an out-of-range, unknown or extra argument reaches the database."""
    out = tools.run_tool(ctx, "th1", call(name, args, "c1"))
    assert out["status"] == "error" and why in out["error"]
    assert logged(con) == [(name, "error", 0)]


# ---- tools: log, replay, timeout, retry --------------------------------------------------


def test_a_finished_call_is_replayed_from_the_log_not_run_again(con, ctx):
    """Fails if the same call id runs its query twice (a resume after a crash would repeat
    work), or if two threads share a call id."""
    c = call("get_outlook", {"city": "t", "days": 2}, "c1")
    first = tools.run_tool(ctx, "th1", c)
    again = tools.run_tool(ctx, "th1", c)
    assert again["rows"] == first["rows"] and again["replayed"] is True
    assert logged(con, "call_id, tool, status, attempts, row_count") == [
        ("th1:c1", "get_outlook", "ok", 1, 2)
    ]
    tools.run_tool(ctx, "th2", c)
    assert [r[0] for r in logged(con, "call_id")] == ["th1:c1", "th2:c1"]
    args = con.execute("select args from agent.tool_call where call_id = 'th1:c1'").fetchall()
    assert args == [({"city": "t", "days": 2},)]


def test_a_slow_query_times_out_is_retried_twice_then_reported_unavailable(con, ctx):
    """Fails if a hung query blocks the assistant, is retried forever, or yields rows."""
    slow = tools.Tool("slow", "sleeps", tools.NoArgs, lambda c, a: c.read("select pg_sleep(5)"))
    ctx.timeout_s = 0.2
    waits = []
    out = tools.run_tool(ctx, "th1", call("slow", {}, "c1"), {"slow": slow}, sleep=waits.append)
    assert out["status"] == "timeout" and "unavailable" in out["error"] and "rows" not in out
    assert waits == [0.5, 1.0]
    assert logged(con) == [("slow", "timeout", 3)]


def test_a_dropped_connection_is_retried_and_then_succeeds(con, ctx):
    """Fails if one transient database error is reported as a failure."""
    seen = []

    def flaky(c, a):
        seen.append(1)
        if len(seen) == 1:
            raise psycopg.OperationalError("connection lost")
        return [{"n": 7}]

    tool = tools.Tool("flaky", "fails once", tools.NoArgs, flaky)
    out = tools.run_tool(ctx, "th1", call("flaky", {}, "c1"), {"flaky": tool}, sleep=lambda s: None)
    assert out["status"] == "ok" and out["rows"] == [{"n": 7}]
    assert logged(con) == [("flaky", "ok", 2)]


def test_a_database_that_stays_down_is_reported_not_guessed(con, ctx):
    """Fails if a tool that cannot reach the data returns anything that looks like data."""

    def down(c, a):
        raise psycopg.OperationalError("server closed the connection")

    tool = tools.Tool("down", "always fails", tools.NoArgs, down)
    out = tools.run_tool(ctx, "th1", call("down", {}, "c1"), {"down": tool}, sleep=lambda s: None)
    assert out["status"] == "error" and "unavailable" in out["error"] and "rows" not in out
    assert logged(con, "tool, status, attempts, error") == [
        ("down", "error", 3, "OperationalError: server closed the connection")
    ]


def test_a_query_the_role_may_not_run_fails_once_without_retries(con, ctx):
    """Fails if a permission error is retried (it cannot fix itself) or returns rows."""
    tool = tools.Tool(
        "raw", "reads raw", tools.NoArgs, lambda c, a: c.read("select * from raw_actual_daily")
    )
    waits = []
    out = tools.run_tool(ctx, "th1", call("raw", {}, "c1"), {"raw": tool}, sleep=waits.append)
    assert out["status"] == "error" and "rows" not in out and waits == []
    assert logged(con) == [("raw", "error", 1)]


# ---- the number check --------------------------------------------------------------------


def test_numbers_in_an_answer_must_come_from_the_sources():
    """Fails if an invented number passes, or a rounded tool number is rejected."""
    src = ['{"high_c": 21.26, "high_f": 70.3, "date": "2026-11-15", "n_days": 1756}']
    assert grounding.unsupported("High near 21.3 C (70.3 F) on 2026-11-15.", src) == []
    assert grounding.unsupported("High near 70 F.", src) == ["70"]  # whole numbers: exact
    assert grounding.unsupported("Based on 1,756 days.", src) == []
    assert grounding.unsupported("High near 21.4 C.", src) == ["21.4"]
    assert grounding.unsupported("About 71 F, give or take 3.", src) == ["71", "3"]
    assert grounding.unsupported("Expect it on 2026-11-16.", src) == ["2026-11-16"]
    assert grounding.unsupported("On Nov 15 it reaches 70.3.", src) == []
    assert grounding.unsupported("On 15 November 2026 it reaches 70.3.", src) == []
    assert grounding.unsupported("On Nov 19 it reaches 70.3.", src) == ["Nov 19"]
    assert grounding.unsupported("A high of 15 F in the 11th hour.", src) == ["15", "11"]
    assert grounding.unsupported("The market 3 stalls may 70.3 open.", src) == ["3"]
    assert grounding.unsupported("It may 99 times rain.", src) == ["99"]
    assert grounding.unsupported("1. Warm day\n2. Cool night", src) == []
    assert grounding.unsupported("A miss of 2.5 either way", ["bias -2.5"]) == []
    assert grounding.unsupported("No data for that day.", []) == []
    assert grounding.unsupported("Use C.", ["x"]) == []


def test_the_users_own_numbers_and_tool_arguments_count_as_sources():
    """Fails if repeating the user's threshold or the requested number of days is flagged."""
    src = ["Will it pass 75 F in the next 3 days?", '{"days": 3}', '{"high_f": 70.3}']
    assert grounding.unsupported("Over 5 days it stays under 70.3 F.", src) == ["5"]
    asked = ["What will the high be on December 25?", '{"date": "2026-12-14"}']
    assert grounding.unsupported("December 25 is past the last day, Dec 14.", asked) == []
    assert grounding.unsupported("On Dec 26 it will be 60 F.", asked) == ["Dec 26", "60"]
    assert grounding.unsupported("No: 70.3 F is below your 75 F line over 3 days.", src) == []


# ---- the graph ---------------------------------------------------------------------------


def quote_high(messages):
    """A scripted model turn: answer with the high from the last tool result."""
    found = [m for m in messages if isinstance(m, ToolMessage) and m.name == "get_outlook"]
    result = json.loads(found[-1].content)
    row = result["rows"][0]
    return AIMessage(content=f"Tomorrow's high is about {row['high_f']} F ({row['high_c']} C).")


def test_agent_calls_a_tool_and_answers_from_its_result(con):
    """Fails if the tool is not run, the answer is not grounded, or the call is not logged."""
    agent = make([call("get_outlook", {"city": "t", "days": 1}, "c1", ai=True), quote_high])
    try:
        out = agent.ask("How warm tomorrow?", thread_id="th1")
    finally:
        agent.close()
    assert out["answer"] == "Tomorrow's high is about 70.3 F (21.3 C)."
    assert out["grounded"] is True and out["unsupported"] == [] and out["model_calls"] == 2
    assert [(c["tool"], c["status"]) for c in out["tool_calls"]] == [("get_outlook", "ok")]
    assert logged(con) == [("get_outlook", "ok", 1)]


def test_an_invented_number_gets_one_rewrite_and_then_passes(con):
    """Fails if a number that is in no tool result reaches the user when the model can fix it."""
    agent = make(
        [
            call("get_outlook", {"city": "t", "days": 1}, "c1", ai=True),
            AIMessage(content="It will reach 99 F tomorrow."),
            quote_high,
        ]
    )
    try:
        out = agent.ask("How warm tomorrow?", thread_id="th1")
        asked = agent.history("th1")
    finally:
        agent.close()
    assert out["answer"] == "Tomorrow's high is about 70.3 F (21.3 C)."
    assert out["grounded"] is True and out["rewrites"] == 1 and out["model_calls"] == 3
    assert [m["role"] for m in asked] == ["user", "assistant"]  # the check stays internal
    assert "99" not in json.dumps(asked)


def test_a_number_that_stays_invented_is_refused_not_shown(con):
    """Fails if the assistant states a number that no tool returned."""
    agent = make(
        [
            call("get_outlook", {"city": "t", "days": 1}, "c1", ai=True),
            AIMessage(content="It will reach 99 F tomorrow."),
            AIMessage(content="It will still reach 99 F tomorrow."),
        ]
    )
    try:
        out = agent.ask("How warm tomorrow?", thread_id="th1")
        shown = agent.history("th1")
    finally:
        agent.close()
    assert out["grounded"] is False and out["unsupported"] == ["99"]  # the correction
    assert not re.search(r"\d", out["answer"])  # the correction note names 99, and that
    assert "99" not in json.dumps(shown)  # must not make it a source, or reach history
    assert "cannot" in out["answer"] and out["model_calls"] == 3
    assert shown[-1]["content"] == out["answer"]
    # both drafts are kept for audit, in order, with what was wrong with each
    assert [(r["draft"], r["unsupported"]) for r in out["rejected"]] == [
        ("It will reach 99 F tomorrow.", ["99"]),
        ("It will still reach 99 F tomorrow.", ["99"]),
    ]


def test_model_failure_gives_a_clear_error_and_no_guess(con):
    """Fails if a model outage produces an answer, or crashes the request."""

    def boom(messages):
        raise RuntimeError("overloaded")

    agent = make([boom])
    try:
        out = agent.ask("How warm tomorrow?", thread_id="th1")
    finally:
        agent.close()
    assert out["error"] == "model unavailable: RuntimeError"
    assert "could not be reached" in out["answer"] and out["grounded"] is True


def test_model_calls_are_capped_per_thread(con):
    """Fails if a model that keeps asking for tools can run without limit. The cap counts
    across questions in the same thread, because the count is part of the saved state."""
    loop = [call("get_data_health", {"city": "t"}, f"c{i}", ai=True) for i in range(10)]
    agent = make(loop, max_model_calls=3)
    try:
        out = agent.ask("Is the data healthy?", thread_id="th1")
        more = agent.ask("And now?", thread_id="th1")
    finally:
        agent.close()
    assert out["model_calls"] == 3 and out["error"] == "model call limit reached"
    assert "limit of 3" in out["answer"]
    assert more["model_calls"] == 3 and more["error"] == "model call limit reached"
    assert len(logged(con)) == 3


def test_a_conversation_is_restored_from_its_checkpoint_by_a_new_process(con):
    """Fails if a thread's history lives in memory only. A second agent object (a new pool,
    as after a restart) must see the first one's turns and send them to the model."""
    first = make([AIMessage(content="Hello.")])
    first.ask("Remember the word zebra-quartz.", thread_id="th1")
    first.close()
    seen = []

    def recall(messages):
        seen.extend(str(m.content) for m in messages)
        return AIMessage(content="You said zebra-quartz.")

    second = make([AIMessage(content="unused"), recall])
    try:
        out = second.ask("What word?", thread_id="th1")
        other = second.history("th-other")
        turns = second.history("th1")
    finally:
        second.close()
    assert out["answer"] == "You said zebra-quartz."
    assert any("zebra-quartz" in s for s in seen)
    assert [m["role"] for m in turns] == ["user", "assistant", "user", "assistant"]
    assert other == []


def test_a_preference_saved_in_one_thread_is_known_in_another(con):
    """Fails if preferences are stored per conversation, or never reach the model."""
    save = call("remember_preference", {"key": "units", "value": "f"}, "c1", ai=True)
    agent = make([save, AIMessage(content="Saved.")])
    agent.ask("Use Fahrenheit from now on.", thread_id="th1")
    agent.close()
    prompts = []

    def answer(messages):
        prompts.extend(str(m.content) for m in messages if isinstance(m, SystemMessage))
        return AIMessage(content="Noted.")

    later = make([answer])
    try:
        later.ask("Hi", thread_id="th2")
        recalled = tools.run_tool(
            later.context("local"), "th2", call("recall_preferences", {}, "r")
        )
        stranger = tools.run_tool(
            later.context("someone"), "th3", call("recall_preferences", {}, "r")
        )
    finally:
        later.close()
    assert any("units: F" in p for p in prompts)
    assert recalled["rows"] == [{"key": "units", "value": "F"}]
    assert stranger["rows"] == []


class Crash(BaseException):
    """Stands in for the process dying: not an Exception, so nothing in the graph handles it."""


def test_a_run_killed_between_two_tools_resumes_without_repeating_the_first(con):
    """Fails if resuming a thread runs a finished tool again, or loses the question."""
    state = {"crash": True}

    def second(c, a):
        if state["crash"]:
            state["crash"] = False
            raise Crash()
        return c.read("select count(*) as n from log_forecast")

    extra = dict(tools.TOOLS)
    extra["second"] = tools.Tool("second", "dies once", tools.NoArgs, second)
    two = AIMessage(
        content="",
        tool_calls=[
            {"name": "get_outlook", "args": {"city": "t", "days": 1}, "id": "c1"},
            {"name": "second", "args": {}, "id": "c2"},
        ],
    )
    agent = make([two, quote_high], tools=extra)
    with pytest.raises(Crash):
        agent.ask("How warm tomorrow?", thread_id="th1")
    agent.close()
    assert logged(con) == [("get_outlook", "ok", 1), ("second", "running", 1)]

    again = make([two, quote_high], tools=extra)
    try:
        out = again.resume("th1")
    finally:
        again.close()
    assert out["answer"] == "Tomorrow's high is about 70.3 F (21.3 C)."
    assert logged(con) == [("get_outlook", "ok", 1), ("second", "ok", 2)]
    assert out["model_calls"] == 2  # the first model call was not repeated either


# ---- site --------------------------------------------------------------------------------


def test_site_chat_endpoint_answers_and_lists_the_thread(con, tmp_path):
    """Fails if the chat API loses the thread id, the tool trail or the history."""
    model = ScriptedModel(
        responses=[call("get_outlook", {"city": "t", "days": 1}, "c1", ai=True), quote_high]
    )
    with TestClient(
        site.create_app(TEST_URL, tmp_path, today=lambda c: TODAY, agent_model=model)
    ) as web:
        r = web.post("/api/agent/ask", json={"question": "How warm tomorrow?"})
        assert r.status_code == 200
        body = r.json()
        assert body["answer"].startswith("Tomorrow's high is about 70.3 F")
        assert body["grounded"] is True and body["tool_calls"][0]["tool"] == "get_outlook"
        assert "rejected" not in body  # refused drafts never leave the server
        thread = web.get("/api/agent/thread", params={"thread_id": body["thread_id"]}).json()
        assert [m["role"] for m in thread["messages"]] == ["user", "assistant"]
        assert web.post("/api/agent/ask", json={"question": "  "}).status_code == 422


def test_site_chat_without_a_key_says_so(con, tmp_path, monkeypatch):
    """Fails if a missing API key shows up as a crash instead of an instruction."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with TestClient(site.create_app(TEST_URL, tmp_path, today=lambda c: TODAY)) as web:
        r = web.post("/api/agent/ask", json={"question": "How warm tomorrow?"})
        assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]
        assert web.get("/api/cities").status_code == 200  # the rest of the site still works


# ---- added after the sprint-04 reviews ---------------------------------------------------


def test_thresholds_keep_the_users_number_and_add_the_other_unit():
    """Fails if a saved threshold comes back as a different number than the user gave
    (85 F must not become 84.9 F), or if the unit, sign or city name is mangled."""

    def saved(key, value):
        return tools.RememberArgs(key=key, value=value).value

    assert saved("hot_day_threshold", "85 F") == "85 F (29.4 C)"
    assert saved("hot_day_threshold", "30°C") == "30 C (86.0 F)"
    assert saved("cold_night_threshold", "-5 c") == "-5 C (23.0 F)"
    assert saved("home_city", " Torrance ") == "torrance"
    assert saved("units", "f") == "F"


def test_tool_definitions_sent_to_the_model_name_every_tool_and_its_arguments():
    """Fails if the model is given no tools, or a tool without its typed arguments."""
    by_name = {s["name"]: s for s in tools.schemas(tools.TOOLS)}
    assert sorted(by_name) == sorted(tools.TOOLS) and len(by_name) == 7
    outlook = by_name["get_outlook"]["input_schema"]
    assert outlook["required"] == ["city"] and outlook["additionalProperties"] is False
    assert (outlook["properties"]["days"]["minimum"], outlook["properties"]["days"]["maximum"]) == (
        1,
        30,
    )
    assert by_name["get_forecast_error_by_lead"]["input_schema"]["properties"]["variable"][
        "enum"
    ] == ["tmax", "tmin"]
    assert all(len(s["description"]) > 30 for s in by_name.values())


def test_a_call_id_reused_for_a_different_call_is_refused_not_answered_from_the_log(con, ctx):
    """Fails if a second call with the same id silently gets the first call's rows."""
    tools.run_tool(ctx, "th1", call("get_outlook", {"city": "t", "days": 1}, "c1"))
    other = tools.run_tool(ctx, "th1", call("get_scoreboard", {"city": "t"}, "c1"))
    assert other["status"] == "error" and "already used" in other["error"] and "rows" not in other
    assert logged(con) == [("get_outlook", "ok", 1)]


def test_long_results_are_cut_with_a_note_and_a_code_error_is_reported(con, ctx):
    """Fails if a huge result is sent whole, the cut is silent, or a bug inside a tool
    escapes instead of becoming an error result (which would strand the conversation)."""
    many = tools.Tool("many", "61 rows", tools.NoArgs, lambda c, a: [{"n": i} for i in range(61)])
    out = tools.run_tool(ctx, "th1", call("many", {}, "c1"), {"many": many})
    assert (out["row_count"], len(out["rows"]), out["note"]) == (61, 60, "first 60 of 61 rows")

    def broken(c, a):
        raise KeyError("oops")

    bug = tools.Tool("bug", "raises", tools.NoArgs, broken)
    waits = []
    out = tools.run_tool(ctx, "th1", call("bug", {}, "c2"), {"bug": bug}, sleep=waits.append)
    assert out["status"] == "error" and "KeyError" in out["error"] and waits == []


def test_a_preference_is_saved_for_the_user_who_stated_it_only(con):
    """Fails if one user's preference is written to, or read by, another user."""
    agent = make([])
    try:
        save = call("remember_preference", {"key": "units", "value": "c"}, "c1")
        tools.run_tool(agent.context("someone"), "th1", save)
        mine = tools.run_tool(agent.context("local"), "th2", call("recall_preferences", {}, "r"))
        theirs = tools.run_tool(
            agent.context("someone"), "th3", call("recall_preferences", {}, "r")
        )
    finally:
        agent.close()
    assert mine["rows"] == [] and theirs["rows"] == [{"key": "units", "value": "C"}]


def test_the_assistant_starts_on_a_database_with_no_marts_yet(tmp_path):
    """Fails if starting the assistant before the first forecast run crashes on a grant."""
    c = fresh_db()  # emptied, marts dropped, nothing rebuilt
    c.close()
    agent = make([])
    try:
        with pytest.raises(psycopg.errors.UndefinedTable):
            agent.context("local").read("select 1 from mart_error_by_lead")
    finally:
        agent.close()


def test_tool_arguments_and_saved_preferences_count_as_sources_in_the_graph(con):
    """Fails if an answer that repeats the number of days asked for, or the user's saved
    threshold, is refused. 5 appears only in the tool arguments, 85 only in the preference."""
    agent = make(
        [
            call(
                "remember_preference", {"key": "hot_day_threshold", "value": "85 F"}, "p", ai=True
            ),
            AIMessage(content="Saved."),
            call("get_outlook", {"city": "t", "days": 5}, "c1", ai=True),
            AIMessage(content="Over the next 5 days the high is 70.3 F, under your 85 F line."),
        ]
    )
    try:
        agent.ask("Warn me above eighty-five Fahrenheit.", thread_id="th1")
        out = agent.ask("Any hot days coming?", thread_id="th1")
    finally:
        agent.close()
    assert out["grounded"] is True and out["rewrites"] == 0
    assert out["answer"].endswith("under your 85 F line.")


def test_only_the_latest_questions_tool_calls_are_reported(con):
    """Fails if a second question in a conversation reports the first question's tools."""
    agent = make(
        [
            call("get_outlook", {"city": "t", "days": 1}, "c1", ai=True),
            quote_high,
            call("get_data_health", {"city": "t"}, "c2", ai=True),
            AIMessage(content="The data is loaded."),
        ]
    )
    try:
        agent.ask("How warm tomorrow?", thread_id="th1")
        out = agent.ask("Is the data fine?", thread_id="th1")
    finally:
        agent.close()
    assert [c["tool"] for c in out["tool_calls"]] == ["get_data_health"]
    assert out["answer"] == "The data is loaded." and out["model_calls"] == 4


def test_a_conversation_recovers_after_a_model_outage(con):
    """Fails if one failed model call leaves the error flag set for the next question."""

    def boom(messages):
        raise RuntimeError("overloaded")

    agent = make([boom, AIMessage(content="Hello again.")])
    try:
        first = agent.ask("Hi", thread_id="th1")
        second = agent.ask("Hi again", thread_id="th1")
    finally:
        agent.close()
    assert first["error"] == "model unavailable: RuntimeError" and first["model_calls"] == 1
    assert (second["error"], second["answer"], second["model_calls"]) == (None, "Hello again.", 2)


def test_a_rejected_request_is_reported_as_a_setup_problem_not_an_outage(con):
    """Fails if a bad key or model name (HTTP 401/404) tells the user to simply try again."""

    class Rejected(Exception):
        status_code = 401

    def boom(messages):
        raise Rejected("invalid x-api-key")

    agent = make([boom])
    try:
        out = agent.ask("Hi", thread_id="th1")
    finally:
        agent.close()
    assert out["error"] == "model rejected the request: Rejected"
    assert "API key" in out["answer"] and "invalid" not in out["answer"]


@pytest.mark.parametrize(
    ("reply", "error", "says"),
    [
        (
            AIMessage(content="", response_metadata={"stop_reason": "refusal"}),
            "model declined",
            "declined",
        ),
        (
            AIMessage(content="The high is 70.", response_metadata={"stop_reason": "max_tokens"}),
            "answer cut off",
            "cut off",
        ),
        (AIMessage(content=""), "empty reply", "returned nothing"),
        (
            AIMessage(content=[{"type": "thinking", "thinking": "hmm 55"}]),
            "empty reply",
            "returned nothing",
        ),
    ],
)
def test_a_reply_that_is_not_an_answer_is_reported_not_shown(con, reply, error, says):
    """Fails if a refusal, a cut-off reply or an empty reply is passed on as the answer."""
    agent = make([reply])
    try:
        out = agent.ask("How warm tomorrow?", thread_id="th1")
        shown = agent.history("th1")
    finally:
        agent.close()
    assert out["error"] == error and says in out["answer"] and "70" not in out["answer"]
    assert shown[-1]["content"] == out["answer"]


def test_a_reply_made_of_blocks_is_read_as_its_text_only(con):
    """Fails if a real model reply (a list of thinking and text blocks) breaks the answer,
    or if a number inside the hidden thinking is treated as part of the answer."""
    blocks = AIMessage(
        content=[
            {"type": "thinking", "thinking": "maybe 55?"},
            {"type": "text", "text": "Tomorrow's high is 70.3 F."},
        ]
    )
    agent = make([call("get_outlook", {"city": "t", "days": 1}, "c1", ai=True), blocks])
    try:
        out = agent.ask("How warm tomorrow?", thread_id="th1")
        shown = agent.history("th1")
    finally:
        agent.close()
    assert out["answer"] == "Tomorrow's high is 70.3 F." and out["grounded"] is True
    assert shown[-1] == {"role": "assistant", "content": "Tomorrow's high is 70.3 F."}


def test_a_new_question_first_finishes_a_run_that_was_cut_off(con):
    """Fails if asking again after a crash leaves a tool call without a result in the
    conversation (the model API rejects every later request on such a thread)."""
    state = {"crash": True}

    def dies(c, a):
        if state["crash"]:
            state["crash"] = False
            raise Crash()
        return [{"n": 1}]

    extra = dict(tools.TOOLS)
    extra["dies"] = tools.Tool("dies", "dies once", tools.NoArgs, dies)
    script = [
        call("dies", {}, "c1", ai=True),
        AIMessage(content="Done."),
        AIMessage(content="Second answer."),
    ]
    agent = make(script, tools=extra)
    with pytest.raises(Crash):
        agent.ask("First question", thread_id="th1")
    agent.close()
    again = make(script, tools=extra)
    try:
        out = again.ask("Second question", thread_id="th1")
        turns = again.history("th1")
        with pytest.raises(LookupError):
            again.resume("no-such-thread")
    finally:
        again.close()
    assert out["answer"] == "Second answer."
    assert [m["content"] for m in turns] == [
        "First question",
        "Done.",
        "Second question",
        "Second answer.",
    ]
    assert logged(con) == [("dies", "ok", 2)]


def test_env_file_is_read_the_way_people_write_it(tmp_path, monkeypatch):
    """Fails if a Notepad BOM, quotes, `export`, a trailing comment or an empty existing
    variable makes a key silently wrong or missing, or if a set variable is replaced."""
    for name in ("WW_A", "WW_B", "WW_C", "WW_D", "WW_E", "WW_F"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WW_KEEP", "mine")
    monkeypatch.setenv("WW_E", "")
    env = tmp_path / ".env"
    env.write_text(
        '\ufeffWW_A=first\n# a comment\n\nexport WW_B=two\nWW_C="q v # x"\n'
        "WW_D=abc # note\nWW_E=filled\nWW_F=\nWW_KEEP=theirs\nnot a line\n",
        encoding="utf-8",
    )
    config.load_env(env)
    got = {k: os.environ.get(k) for k in ("WW_A", "WW_B", "WW_C", "WW_D", "WW_E", "WW_F")}
    assert got == {
        "WW_A": "first",
        "WW_B": "two",
        "WW_C": "q v # x",
        "WW_D": "abc",
        "WW_E": "filled",
        "WW_F": None,
    }
    assert os.environ["WW_KEEP"] == "mine"
    config.load_env(tmp_path / "missing.env")  # no file: nothing happens


def test_site_reports_a_model_failure_in_the_reply_and_validates_input(con, tmp_path):
    """Fails if a model outage becomes an HTTP 500, or oversized input is accepted."""

    def boom(messages):
        raise RuntimeError("overloaded")

    model = ScriptedModel(responses=[boom])
    with TestClient(
        site.create_app(TEST_URL, tmp_path, today=lambda c: TODAY, agent_model=model)
    ) as web:
        r = web.post("/api/agent/ask", json={"question": "  How warm?  "})
        assert r.status_code == 200 and r.json()["error"] == "model unavailable: RuntimeError"
        assert r.json()["tool_calls"] == []
        thread = web.get("/api/agent/thread", params={"thread_id": r.json()["thread_id"]}).json()
        assert thread["messages"][0] == {"role": "user", "content": "How warm?"}
        assert web.post("/api/agent/ask", json={"question": "x" * 2001}).status_code == 422
        assert web.get("/api/agent/thread", params={"thread_id": "t" * 65}).status_code == 422
        assert web.get("/api/agent/thread", params={"thread_id": "nobody"}).json()["messages"] == []
