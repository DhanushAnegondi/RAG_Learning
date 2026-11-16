"""Sprint 02 data layer: weather-model column, cleaning rules, forecast log, verification marts."""

from datetime import date

import pandas as pd
import pytest
from conftest import fresh_db

from weatherwise import ingest, observations, warehouse
from weatherwise.config import CITIES

FLAT = [30.0] * 24


def hourly(city, day, lead, temps, model=None) -> pd.DataFrame:
    start = pd.Timestamp(day)
    df = pd.DataFrame(
        {
            "city": city,
            "ts_local": [start + pd.Timedelta(hours=h) for h in range(len(temps))],
            "lead_days": lead,
            "temp_c": temps,
        }
    )
    return df if model is None else df.assign(model=model)


def actual(city, rows) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "city": city,
            "date": [pd.Timestamp(d) for d, _, _ in rows],
            "tmax_c": [mx for _, mx, _ in rows],
            "tmin_c": [mn for _, _, mn in rows],
            "precip_mm": 0.0,
        }
    )


def log_row(kind, issued, day, lead, pred, lo, hi, published, variable="tmax") -> dict:
    return {
        "city": "t",
        "kind": kind,
        "issued_on": pd.Timestamp(issued),
        "date": pd.Timestamp(day),
        "variable": variable,
        "lead_days": lead,
        "pred_c": pred,
        "lo_c": lo,
        "hi_c": hi,
        "published_c": published,
        "method": "raw",
        "logged_at": pd.Timestamp("2026-11-14 08:00"),
    }


@pytest.fixture
def con():
    c = fresh_db()
    yield c
    c.close()


def test_torrance_is_configured_in_fahrenheit():
    """Fails if Torrance is missing, mislocated, or shown in Celsius by default."""
    city = CITIES["torrance"]
    assert (round(city.latitude, 2), round(city.longitude, 2)) == (33.84, -118.34)
    assert city.timezone == "America/Los_Angeles"
    assert city.unit == "F"
    assert CITIES["bengaluru"].unit == "C"


def test_parse_previous_runs_splits_weather_models_by_column_suffix():
    """Fails if two models' series are mixed up or the model label is lost."""
    payload = {
        "hourly": {
            "time": ["2025-01-01T00:00", "2025-01-01T01:00"],
            "temperature_2m_previous_day1_best_match": [10.0, 11.0],
            "temperature_2m_previous_day1_gfs_seamless": [20.0, None],
        }
    }
    df = ingest.parse_previous_runs(payload, "t", [1], models=("best_match", "gfs_seamless"))
    got = sorted(zip(df["model"], df["temp_c"], strict=True))
    assert got == [("best_match", 10.0), ("best_match", 11.0), ("gfs_seamless", 20.0)]


def test_parse_daily_models_reads_one_series_per_model():
    """Fails if a model's daily max is read from another model's column."""
    payload = {
        "daily": {
            "time": ["2025-01-02"],
            "temperature_2m_max_best_match": [25.0],
            "temperature_2m_min_best_match": [15.0],
            "temperature_2m_max_gfs_seamless": [27.5],
            "temperature_2m_min_gfs_seamless": [14.0],
        }
    }
    df = ingest.parse_daily_models(payload, "t", ("best_match", "gfs_seamless"))
    got = df.set_index("model")[["tmax_c", "tmin_c"]].to_dict("index")
    assert got == {
        "best_match": {"tmax_c": 25.0, "tmin_c": 15.0},
        "gfs_seamless": {"tmax_c": 27.5, "tmin_c": 14.0},
    }


def test_two_models_for_the_same_hour_both_survive_and_default_is_best_match(con):
    """Fails if model drops out of the key (one model overwrites the other) or a frame without
    a model column is not stored as best_match."""
    warehouse.load(con, "published_hourly", hourly("t", "2025-01-01", 1, FLAT))
    n = warehouse.load(con, "published_hourly", hourly("t", "2025-01-01", 1, FLAT, "gfs_seamless"))
    assert n == 48
    models = con.execute("select distinct model from raw_published_hourly order by 1").fetchall()
    assert models == [("best_match",), ("gfs_seamless",)]


def test_error_mart_uses_only_the_published_model(con):
    """Fails if another weather model's forecast leaks into the published-forecast error.

    best_match flat 31 vs actual 30 -> error +1. gfs flat 40 must not change that.
    """
    warehouse.load(con, "published_hourly", hourly("t", "2025-01-01", 1, [31.0] * 24))
    warehouse.load(
        con, "published_hourly", hourly("t", "2025-01-01", 1, [40.0] * 24, "gfs_seamless")
    )
    warehouse.load(con, "actual_daily", actual("t", [("2025-01-01", 30.0, 20.0)]))
    warehouse.build_models(con)
    rows = con.execute("select error_c from mart_forecast_error where variable = 'tmax'").fetchall()
    assert rows == [(1.0,)]


def test_model_pairs_put_other_models_beside_the_published_forecast(con):
    """Fails if fc_gfs is not the gfs daily max, or a missing model is not null.

    best_match max 31, gfs max 33 (hour 5), no ecmwf rows; actual max 30.
    """
    gfs = [20.0] * 24
    gfs[5] = 33.0
    warehouse.load(con, "published_hourly", hourly("t", "2025-01-01", 2, [31.0] * 24))
    warehouse.load(con, "published_hourly", hourly("t", "2025-01-01", 2, gfs, "gfs_seamless"))
    warehouse.load(con, "actual_daily", actual("t", [("2025-01-01", 30.0, 19.0)]))
    warehouse.build_models(con)
    row = con.execute(
        "select lead_days, forecast_c, fc_gfs, fc_ecmwf, fc_gem, actual_c from mart_model_pairs "
        "where variable = 'tmax'"
    ).fetchall()
    assert row == [(2, 31.0, 33.0, None, None, 30.0)]
    tmin = con.execute(
        "select forecast_c, fc_gfs, actual_c from mart_model_pairs where variable = 'tmin'"
    ).fetchall()
    assert tmin == [(31.0, 20.0, 19.0)]


def test_cleaning_rejects_impossible_actuals_and_lists_the_reason(con):
    """Fails if an impossible reading reaches the models, or is dropped without a trace."""
    rows = [
        ("2025-01-01", 30.0, 20.0),  # fine
        ("2025-01-02", 99.0, 20.0),  # sensor nonsense
        ("2025-01-03", 15.0, 22.0),  # max below min
        ("2025-01-04", 10.0, -75.0),  # impossible low, max still above min
    ]
    warehouse.load(con, "actual_daily", actual("t", rows))
    warehouse.build_models(con)
    kept = con.execute("select date from stg_actual_daily").fetchall()
    assert kept == [(date(2025, 1, 1),)]
    issues = con.execute(
        "select cast(seen_at as date), reason from stg_quality_issues order by seen_at"
    ).fetchall()
    assert issues == [
        (date(2025, 1, 2), "temperature outside -60..60 C"),
        (date(2025, 1, 3), "max below min"),
        (date(2025, 1, 4), "temperature outside -60..60 C"),
    ]


def test_cleaning_drops_a_forecast_day_with_one_impossible_hour(con):
    """Fails if a 999 C glitch becomes the day's max instead of making the day unusable."""
    temps = [30.0] * 24
    temps[7] = 999.0
    warehouse.load(con, "published_hourly", hourly("t", "2025-01-01", 1, temps))
    warehouse.load(con, "published_hourly", hourly("t", "2025-01-02", 1, FLAT))
    warehouse.build_models(con)
    days = con.execute("select date, tmax_c from stg_published_daily").fetchall()
    assert days == [(date(2025, 1, 2), 30.0)]


def test_data_quality_counts_rejected_and_missing_days(con):
    """Fails if the health table miscounts.

    Actuals: 1 Jan ok, 2 Jan rejected (99 C), 3 Jan never arrived, 4 Jan ok.
    -> 3 raw rows, 2 usable, 1 rejected, calendar span 4 days so 2 missing.
    """
    rows = [("2025-01-01", 30.0, 20.0), ("2025-01-02", 99.0, 20.0), ("2025-01-04", 31.0, 21.0)]
    warehouse.load(con, "actual_daily", actual("t", rows))
    warehouse.build_models(con)
    got = con.execute(
        "select raw_rows, usable_days, rejected_days, missing_days from mart_data_quality"
    ).fetchall()
    assert got == [(3, 2, 1, 2)]


def test_forecast_log_keeps_live_rows_when_hindcasts_are_replayed(con):
    """Fails if replaying hindcasts deletes or overwrites a forecast that was issued live."""
    live = pd.DataFrame([log_row("live", "2026-11-13", "2026-11-14", 1, 25.0, 23.0, 27.0, 24.0)])
    old = pd.DataFrame(
        [
            log_row("hindcast", "2026-11-13", "2026-11-14", 1, 99.0, 98.0, 100.0, 24.0),
            log_row("hindcast", "2026-11-01", "2026-11-02", 1, 21.0, 20.0, 22.0, 20.5),
        ]
    )
    new = pd.DataFrame([log_row("hindcast", "2026-11-13", "2026-11-14", 1, 26.0, 24.0, 28.0, 24.0)])
    warehouse.load(con, "forecast_log", live)
    warehouse.load(con, "forecast_log", old)
    n = warehouse.load(con, "forecast_log", new)
    assert n == 2  # the 2 Nov hindcast from the earlier replay is gone
    rows = con.execute("select kind, pred_c from log_forecast order by kind").fetchall()
    assert rows == [("hindcast", 26.0), ("live", 25.0)]


def test_verification_compares_the_entry_with_the_forecast_and_prefers_live(con):
    """Fails if errors, the inside-range flag or the live-over-hindcast rule are wrong.

    User saw max 26.0 on 14 Nov. Live lead-1 forecast 25.0 (range 23-27, published 24.0):
    our error -1.0, published error -2.0, inside. A hindcast for the same day and lead (30.0)
    must be ignored. Lead-3 hindcast 29.5 (range 27-28.9): error +3.5, outside.
    """
    rows = [
        log_row("live", "2026-11-13", "2026-11-14", 1, 25.0, 23.0, 27.0, 24.0),
        log_row("hindcast", "2026-11-13", "2026-11-14", 1, 30.0, 29.0, 31.0, 24.0),
        log_row("hindcast", "2026-11-11", "2026-11-14", 3, 29.5, 27.0, 28.9, None),
    ]
    warehouse.load(con, "forecast_log", pd.DataFrame(rows))
    warehouse.load(con, "actual_daily", actual("t", [("2026-11-14", 26.5, 15.0)]))
    observations.save(
        con, "t", date(2026, 11, 14), 26.0, None, "C", today=date(2026, 11, 14), note="porch"
    )
    warehouse.build_models(con)
    got = con.execute(
        "select lead_days, kind, our_error_c, published_error_c, inside_range, era5_c "
        "from mart_verification order by lead_days"
    ).fetchall()
    assert got == [(1, "live", -1.0, -2.0, True, 26.5), (3, "hindcast", 3.5, None, False, 26.5)]
    score = con.execute(
        "select lead_days, n_checks, our_mae_c, published_mae_c, share_inside_range, "
        "your_reading_minus_era5_c from mart_scoreboard order by lead_days"
    ).fetchall()
    assert score == [(1, 1, 1.0, 2.0, 1.0, -0.5), (3, 1, 3.5, None, 0.0, -0.5)]


def test_observation_in_fahrenheit_is_stored_in_celsius_and_reentry_edits(con):
    """Fails if 77 F is not stored as 25 C, or typing the day again adds a second row."""
    today = date(2026, 11, 14)
    observations.save(con, "t", date(2026, 11, 13), 77.0, 59.0, "F", today=today)
    observations.save(con, "t", date(2026, 11, 13), 86.0, 59.0, "F", today=today)
    rows = con.execute("select date, tmax_c, tmin_c from raw_user_observation").fetchall()
    assert rows == [(date(2026, 11, 13), 30.0, 15.0)]


@pytest.mark.parametrize(
    ("day", "tmax", "tmin", "unit", "why"),
    [
        (date(2026, 11, 15), 25.0, 15.0, "C", "future"),
        (date(2026, 11, 13), None, None, "C", "at least one"),
        (date(2026, 11, 13), 15.0, 25.0, "C", "below"),
        (date(2026, 11, 13), 200.0, 15.0, "F", "outside"),
        (date(2026, 11, 13), 25.0, 15.0, "K", "unit"),
    ],
)
def test_observation_rejects_bad_entries_with_a_reason(con, day, tmax, tmin, unit, why):
    """Fails if a future date, an empty entry, max below min, an impossible value (200 F is
    93 C) or an unknown unit is stored."""
    with pytest.raises(ValueError, match=why):
        observations.save(con, "t", day, tmax, tmin, unit, today=date(2026, 11, 14))
    assert con.execute("select count(*) from raw_user_observation").fetchall() == [(0,)]


def test_observation_delete_removes_only_that_day(con):
    today = date(2026, 11, 14)
    observations.save(con, "t", date(2026, 11, 12), 25.0, None, "C", today=today)
    observations.save(con, "t", date(2026, 11, 13), 26.0, None, "C", today=today)
    observations.delete(con, "t", date(2026, 11, 12))
    assert con.execute("select date from raw_user_observation").fetchall() == [
        (date(2026, 11, 13),)
    ]


def test_backup_restores_entries_and_live_forecasts_into_a_new_database(con, tmp_path):
    """Fails if the user's entries or issued forecasts are lost when the database is rebuilt.
    Hindcasts are not backed up: they are replayed from data."""
    observations.save(con, "t", date(2026, 11, 13), 25.0, 15.0, "C", today=date(2026, 11, 14))
    rows = [
        log_row("live", "2026-11-13", "2026-11-14", 1, 25.0, 23.0, 27.0, 24.0),
        log_row("hindcast", "2026-11-01", "2026-11-02", 1, 21.0, 20.0, 22.0, 20.5),
    ]
    warehouse.load(con, "forecast_log", pd.DataFrame(rows))
    warehouse.backup(con, tmp_path)
    fresh = fresh_db()
    warehouse.restore(fresh, tmp_path)
    assert fresh.execute("select tmax_c, tmin_c from raw_user_observation").fetchall() == [
        (25.0, 15.0)
    ]
    assert fresh.execute("select kind, pred_c, published_c from log_forecast").fetchall() == [
        ("live", 25.0, 24.0)
    ]
    warehouse.restore(fresh, tmp_path)  # idempotent
    assert fresh.execute("select count(*) from log_forecast").fetchall() == [(1,)]
