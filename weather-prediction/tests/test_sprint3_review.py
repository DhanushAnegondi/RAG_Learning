"""Tests added after the sprint-03 test review: atomic loads, migration order, the reset guard,
checksums of every fetched table, an offline end-to-end run, and the remaining site endpoints."""

from datetime import date

import numpy as np
import pandas as pd
import psycopg
import pytest
from conftest import TEST_URL, fresh_db
from fastapi.testclient import TestClient

from weatherwise import observations, pipeline, site, warehouse
from weatherwise.config import City


@pytest.fixture
def con():
    c = fresh_db()
    yield c
    c.close()


def log_row(kind, issued, day, lead, pred, variable="tmax", city="t") -> dict:
    return {
        "city": city,
        "kind": kind,
        "issued_on": pd.Timestamp(issued),
        "date": pd.Timestamp(day),
        "variable": variable,
        "lead_days": lead,
        "pred_c": pred,
        "lo_c": pred - 2,
        "hi_c": pred + 2,
        "published_c": pred - 1,
        "method": "raw",
        "logged_at": pd.Timestamp("2026-11-14 08:00"),
    }


def test_a_load_that_fails_halfway_undoes_its_own_delete(con):
    """Fails if the forecast-log load is not one transaction. The loader first deletes the
    city's old hindcasts, then inserts. Here the insert fails (variable 'wind' breaks a check
    constraint on the target, which the temp table does not have), so the delete must be
    undone and the old hindcast must still be there."""
    old = pd.DataFrame([log_row("hindcast", "2026-11-01", "2026-11-02", 1, 21.0)])
    warehouse.load(con, "forecast_log", old)
    bad = pd.DataFrame(
        [
            log_row("hindcast", "2026-11-05", "2026-11-06", 1, 30.0),
            log_row("hindcast", "2026-11-05", "2026-11-06", 1, 30.0, variable="wind"),
        ]
    )
    with pytest.raises(psycopg.Error):
        warehouse.load(con, "forecast_log", bad)
    assert con.execute("select date, pred_c from log_forecast").fetchall() == [
        (date(2026, 11, 2), 21.0)
    ]


def test_migrations_run_in_name_order_and_stop_at_the_first_failure(con, tmp_path):
    """Fails if files run out of order (910 needs the table 905 creates), or a file after a
    failing one is applied anyway."""
    (tmp_path / "910_add.sql").write_text("alter table zz_ord add b integer;", encoding="utf-8")
    (tmp_path / "905_make.sql").write_text("create table zz_ord (a integer);", encoding="utf-8")
    try:
        assert warehouse.migrate(con, tmp_path) == ["905_make.sql", "910_add.sql"]
        (tmp_path / "920_bad.sql").write_text("select 1 / 0;", encoding="utf-8")
        (tmp_path / "930_late.sql").write_text(
            "create table zz_late (a integer);", encoding="utf-8"
        )
        with pytest.raises(psycopg.Error):
            warehouse.migrate(con, tmp_path)
        assert con.execute("select to_regclass('zz_late')").fetchall() == [(None,)]
    finally:
        con.execute("drop table if exists zz_ord, zz_late")
        con.execute("delete from schema_migration where name like '9%'")


class FakeCon:
    """Stands in for a connection to the real warehouse, so the guard can be tested without
    ever pointing a truncate at real data."""

    def __init__(self, name: str):
        self.name, self.statements = name, []

    def execute(self, sql, params=None):
        self.statements.append(sql)
        return self

    def fetchall(self):
        return [(self.name,)]


def test_reset_runs_no_sql_on_a_database_that_is_not_for_tests():
    """Fails if reset() stops calling the guard: on a database named 'weatherwise' it must
    raise after the name lookup and send nothing else."""
    fake = FakeCon("weatherwise")
    with pytest.raises(RuntimeError, match="_test"):
        warehouse.reset(fake)
    assert fake.statements == ["select current_database()"]


def hourly(day: str, temps: list[float], model: str = "best_match") -> pd.DataFrame:
    start = pd.Timestamp(day)
    return pd.DataFrame(
        {
            "city": "t",
            "model": model,
            "ts_local": [start + pd.Timedelta(hours=h) for h in range(len(temps))],
            "lead_days": 1,
            "temp_c": temps,
        }
    )


def test_checksum_sees_a_changed_forecast_hour_and_a_changed_live_value(con):
    """Fails if the digest covers only the actuals table, or a corrected forecast hour is not
    replaced on reload."""
    warehouse.load(con, "published_hourly", hourly("2025-01-01", [20.0, 21.0]))
    live = pd.DataFrame(
        {
            "city": "t",
            "issued_on": [pd.Timestamp("2025-01-01")],
            "date": [pd.Timestamp("2025-01-02")],
            "tmax_c": [25.0],
            "tmin_c": [15.0],
            "precip_mm": [0.0],
        }
    )
    warehouse.load(con, "live_forecast", live)
    first = warehouse.checksum(con)
    assert (first["raw_published_hourly"][0], first["raw_live_forecast"][0]) == (2, 1)
    warehouse.load(con, "published_hourly", hourly("2025-01-01", [20.0, 22.5]))
    warehouse.load(con, "live_forecast", live.assign(tmin_c=14.0))
    second = warehouse.checksum(con)
    assert second["raw_published_hourly"] != first["raw_published_hourly"]
    assert second["raw_live_forecast"] != first["raw_live_forecast"]
    temps = con.execute("select temp_c from raw_published_hourly order by ts_local").fetchall()
    assert temps == [(20.0,), (22.5,)]


def test_loaded_at_moves_only_when_a_value_changed(con):
    """Fails if an identical reload rewrites every row (loaded_at would lie about freshness),
    or a changed value does not refresh it."""
    df = pd.DataFrame(
        {
            "city": "t",
            "date": [pd.Timestamp("2025-01-01")],
            "tmax_c": [29.0],
            "tmin_c": [19.0],
            "precip_mm": [0.0],
        }
    )
    stamp = "select loaded_at from raw_actual_daily"
    warehouse.load(con, "actual_daily", df)
    first = con.execute(stamp).fetchall()
    warehouse.load(con, "actual_daily", df)
    assert con.execute(stamp).fetchall() == first
    warehouse.load(con, "actual_daily", df.assign(tmax_c=30.0))
    assert con.execute(stamp).fetchall() != first


# ---- offline end-to-end run -------------------------------------------------------------

TODAY = date(2025, 12, 31)


def seed_small_city(con) -> None:
    """Four years of synthetic actuals, three years of 2-lead forecasts that run 1.5 C too warm,
    and a live forecast issued TODAY. Small enough to run in seconds."""
    rng = np.random.default_rng(7)
    days = pd.date_range("2022-01-01", "2025-12-30", freq="D")
    tmax = 22 + 5 * np.sin(2 * np.pi * days.day_of_year / 365.25) + rng.normal(0, 1.0, len(days))
    actual = pd.DataFrame(
        {"city": "t", "date": days, "tmax_c": tmax, "tmin_c": tmax - 8, "precip_mm": 0.0}
    )
    warehouse.load(con, "actual_daily", actual)
    fc = actual[actual["date"] >= "2023-01-01"]
    parts = []
    for lead in (1, 2):
        hi = fc["tmax_c"].to_numpy() + 1.5 + rng.normal(0, 0.4 * lead, len(fc))
        lo = hi - 8
        for hour in range(24):
            parts.append(
                pd.DataFrame(
                    {
                        "city": "t",
                        "ts_local": fc["date"].to_numpy() + np.timedelta64(hour, "h"),
                        "lead_days": lead,
                        "temp_c": hi if hour == 14 else lo if hour == 5 else (hi + lo) / 2,
                    }
                )
            )
    warehouse.load(con, "published_hourly", pd.concat(parts, ignore_index=True))
    ahead = pd.date_range("2025-12-31", periods=6, freq="D")
    live = pd.DataFrame(
        {
            "city": "t",
            "issued_on": pd.Timestamp(TODAY),
            "date": ahead,
            "tmax_c": 24.0,
            "tmin_c": 16.0,
            "precip_mm": 0.0,
        }
    )
    warehouse.load(con, "live_forecast", live)
    warehouse.build_models(con)


def test_run_city_logs_live_and_replayed_forecasts_and_replaces_the_leaderboard(con, monkeypatch):
    """Fails if a run does not log today's outlook, files a replay under the wrong issue day,
    replays a day the models were trained on, leaves the warm bias in, or doubles the
    leaderboard on a second run. Two leads and a 10-day horizon keep it fast."""
    monkeypatch.setattr(pipeline, "SHORT_LEADS", 2)
    monkeypatch.setattr(pipeline, "HORIZON", 10)
    seed_small_city(con)
    city = City("t", 0.0, 0.0, "UTC")
    res = pipeline.run_city(con, city, TODAY, use_lstm=False)

    live = con.execute(
        "select count(*), min(issued_on), max(issued_on), max(lead_days) from log_forecast "
        "where kind = 'live'"
    ).fetchall()
    assert live == [(20, TODAY, TODAY, 10)]  # 10 days x high and low
    wrong_issue_day = con.execute(
        "select count(*) from log_forecast where issued_on <> date - lead_days"
    ).fetchall()
    assert wrong_issue_day == [(0,)]
    # the long backtest forecasts from its last observed day, so it is logged one lead
    # shorter: leads 3..9 here, never 10
    replay_leads = con.execute(
        "select distinct lead_days from log_forecast where kind = 'hindcast' order by 1"
    ).fetchall()
    assert [r[0] for r in replay_leads] == list(range(1, 10))
    first_replay = con.execute(
        "select min(date) from log_forecast where kind = 'hindcast'"
    ).fetchall()[0][0]
    assert first_replay >= res["test_start"].date() == date(2024, 12, 31)

    short = res["summary"]["tmax"]["short"]
    assert (short["corrected_mae_c"] < short["published_mae_c"] - 0.5).all()  # bias removed
    assert (short["published_bias_c"] > 1.2).all() and (short["corrected_bias_c"].abs() < 0.4).all()

    board = con.execute("select count(*) from app_model_eval").fetchall()
    pipeline.run_city(con, city, TODAY, use_lstm=False)
    assert con.execute("select count(*) from app_model_eval").fetchall() == board
    assert con.execute("select city, today from app_run").fetchall() == [("t", TODAY)]
    assert con.execute("select count(*) from log_forecast where kind = 'live'").fetchall() == [
        (20,)
    ]


# ---- site: remaining endpoints, error paths, pool ---------------------------------------


@pytest.fixture
def client(tmp_path):
    con = fresh_db()
    rows = [
        log_row("hindcast", "2026-11-12", "2026-11-13", 1, 25.0, city="torrance"),
        log_row("live", "2026-11-14", "2026-11-15", 1, 22.0, city="torrance"),
    ]
    warehouse.load(con, "forecast_log", pd.DataFrame(rows))
    actual = pd.DataFrame(
        {
            "city": "torrance",
            "date": [pd.Timestamp("2026-11-13"), pd.Timestamp("2026-11-12")],
            "tmax_c": [26.0, 99.0],
            "tmin_c": [15.0, 15.0],
            "precip_mm": 0.0,
        }
    )
    warehouse.load(con, "actual_daily", actual)
    board = pd.DataFrame(
        {
            "city": "torrance",
            "variable": "tmax",
            "lead_days": 1,
            "method": ["raw", "blend"],
            "cv_mae_c": [1.3, 1.1],
            "test_mae_c": [1.29, 1.14],
            "test_days": 365,
            "chosen": [False, True],
            "coverage_pct": [None, 73.7],
        }
    )
    warehouse.load(con, "model_eval", board)
    con.close()
    app = site.create_app(TEST_URL, data_dir=tmp_path, today=lambda city: date(2026, 11, 14))
    with TestClient(app) as c:
        yield c


def test_history_pairs_the_replayed_forecast_with_what_happened(client):
    """Fails if the track-record chart reads the wrong forecast kind or loses the actual."""
    rows = client.get("/api/history", params={"city": "torrance"}).json()
    assert [(r["date"], r["pred_c"], r["published_c"], r["actual_c"]) for r in rows] == [
        ("2026-11-13", 25.0, 24.0, 26.0)
    ]


def test_leaderboard_quality_and_issues_endpoints_return_the_stored_rows(client):
    """Fails if these pages' queries break in the Postgres dialect or drop the chosen flag."""
    board = client.get("/api/leaderboard", params={"city": "torrance"}).json()
    assert [(r["method"], r["test_mae_c"], r["chosen"], r["coverage_pct"]) for r in board] == [
        ("blend", 1.14, True, 73.7),
        ("raw", 1.29, False, None),
    ]
    quality = client.get("/api/quality", params={"city": "torrance"}).json()
    assert [(q["raw_rows"], q["usable_days"], q["rejected_days"]) for q in quality] == [(2, 1, 1)]
    issues = client.get("/api/issues", params={"city": "torrance"}).json()
    assert [(i["reason"], i["rejected_rows"]) for i in issues] == [
        ("temperature outside -60..60 C", 1)
    ]
    assert client.get("/api/error-by-lead", params={"city": "torrance"}).json() == []


def test_check_endpoint_returns_nothing_before_an_entry_and_the_comparison_after(client):
    params = {"city": "torrance", "date": "2026-11-13"}
    assert client.get("/api/check", params=params).json() == {"checks": []}
    client.post("/api/observations", json={**params, "tmax": 27.0, "unit": "C"})
    checks = client.get("/api/check", params=params).json()["checks"]
    assert [(c["kind"], c["our_error_c"], c["era5_c"]) for c in checks] == [
        ("hindcast", -2.0, 26.0)
    ]


@pytest.mark.parametrize(
    "path",
    ["history", "leaderboard", "error-by-lead", "quality", "issues", "scoreboard", "outlook"],
)
def test_unknown_city_is_a_404_on_every_page(client, path):
    r = client.get(f"/api/{path}", params={"city": "atlantis"})
    assert r.status_code == 404
    assert "atlantis" in r.json()["detail"]


def test_failed_requests_give_their_connection_back(client):
    """Fails if an error path keeps its pooled connection: the pool holds 4, so after 12
    refused entries a normal request would hang or fail."""
    bad = {"city": "torrance", "date": "2026-11-30", "tmax": 20, "unit": "C"}  # future day
    for _ in range(12):
        assert client.post("/api/observations", json=bad).status_code == 400
    assert client.get("/api/observations", params={"city": "torrance"}).status_code == 200


def test_records_keeps_midnight_timestamps_as_timestamps():
    """Fails if a time of 00:00:30 is shortened to a date (the time of an entry was lost)."""
    df = pd.DataFrame(
        {
            "d": [date(2026, 11, 13)],
            "t": [pd.Timestamp("2026-11-13 00:00:30")],
            "x": [np.float64(1.5)],
            "n": [None],
        }
    )
    assert site.records(df) == [
        {"d": "2026-11-13", "t": "2026-11-13T00:00:30", "x": 1.5, "n": None}
    ]


def test_a_live_forecast_is_written_once_and_a_same_day_rerun_cannot_change_it(con):
    """Fails if a second run on the same day rewrites a forecast that was already issued (the
    check-a-day comparison would then be against a number changed after the fact). A hindcast
    for the same key is still replaced, and a new issue day adds a new live row."""
    first = pd.DataFrame([log_row("live", "2026-11-14", "2026-11-15", 1, 22.0)])
    again = pd.DataFrame([log_row("live", "2026-11-14", "2026-11-15", 1, 30.0)])
    next_day = pd.DataFrame([log_row("live", "2026-11-15", "2026-11-16", 1, 19.0)])
    warehouse.load(con, "forecast_log", first)
    warehouse.load(con, "forecast_log", again)
    warehouse.load(con, "forecast_log", next_day)
    rows = con.execute("select issued_on, pred_c from log_forecast order by issued_on").fetchall()
    assert rows == [(date(2026, 11, 14), 22.0), (date(2026, 11, 15), 19.0)]


def test_long_range_candidates_share_rows_and_mix_is_their_average():
    """Fails if the LSTM and the simple model are scored on different days, or 'mix' is not the
    plain average of the two forecasts."""
    rng = np.random.default_rng(3)
    idx = pd.date_range("2021-01-01", periods=1100, freq="D")
    x = np.zeros(len(idx))
    for i in range(1, len(idx)):
        x[i] = 0.8 * x[i - 1] + rng.normal(0, 1.0)
    series = pd.Series(22 + 5 * np.sin(2 * np.pi * idx.day_of_year / 365.25) + x, index=idx)
    out, fitted = pipeline.long_backtests(series[:900], series, series.index[900:1000:10], True)
    assert set(out) == {"decay", "lstm", "mix"} and "net" in fitted
    keys = ["origin", "lead_days", "date", "actual_c"]
    assert out["decay"][keys].equals(out["lstm"][keys]) and len(out["decay"]) == 10 * 30
    assert np.allclose(out["mix"]["pred_c"], (out["decay"]["pred_c"] + out["lstm"]["pred_c"]) / 2)
    assert not np.allclose(out["decay"]["pred_c"], out["lstm"]["pred_c"])


def test_long_range_choice_at_exactly_the_margin_and_a_note_that_cannot_be_stored(con):
    """Fails if a challenger exactly 2% better is refused, or a note with a NUL character
    reaches the database driver (a 500) instead of being refused with a reason."""
    assert pipeline.choose_long({"decay": 1.0, "lstm": 0.98}) == "lstm"
    with pytest.raises(ValueError, match="note"):
        observations.save(
            con, "t", date(2026, 11, 13), 25.0, None, "C", today=date(2026, 11, 14), note="a\x00b"
        )
