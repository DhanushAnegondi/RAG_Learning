"""SQL layer on a real Postgres engine: raw loads, staging aggregation, error marts."""

import pandas as pd
import psycopg
import pytest
from conftest import fresh_db

from weatherwise.warehouse import build_models, load, snapshot


def hourly(city: str, day: str, lead: int, temps: list[float]) -> pd.DataFrame:
    start = pd.Timestamp(day)
    return pd.DataFrame(
        {
            "city": city,
            "ts_local": [start + pd.Timedelta(hours=h) for h in range(len(temps))],
            "lead_days": lead,
            "temp_c": temps,
        }
    )


def actual(city: str, rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "city": city,
            "date": [pd.Timestamp(d) for d, _, _ in rows],
            "tmax_c": [mx for _, mx, _ in rows],
            "tmin_c": [mn for _, _, mn in rows],
            "precip_mm": 0.0,
        }
    )


# 24 hours: min 18.0 at hour 0, max 31.0 at hour 13. Hand-checkable.
DAY1_TEMPS = [18.0 + h for h in range(14)] + [30.0 - h for h in range(10)]


@pytest.fixture
def con():
    c = fresh_db()
    yield c
    c.close()


def test_load_is_idempotent_and_replaces_changed_rows(con):
    """Fails if a rerun duplicates rows or a corrected value is not replaced."""
    df = actual("c", [("2025-01-01", 29.0, 19.0), ("2025-01-02", 28.0, 18.0)])
    assert load(con, "actual_daily", df) == 2
    before = con.execute("select sum(tmax_c), count(*) from raw_actual_daily").fetchall()[0]
    assert load(con, "actual_daily", df) == 2
    assert con.execute("select sum(tmax_c), count(*) from raw_actual_daily").fetchall()[0] == before
    df.loc[0, "tmax_c"] = 30.0
    assert load(con, "actual_daily", df) == 2
    got = con.execute(
        "select tmax_c from raw_actual_daily where date = date '2025-01-01'"
    ).fetchall()[0]
    assert got == (30.0,)


def test_load_duplicate_key_in_one_batch_fails_loudly(con):
    """Fails if two rows for the same city+date are silently collapsed."""
    df = actual("c", [("2025-01-01", 29.0, 19.0), ("2025-01-01", 30.0, 19.0)])
    with pytest.raises(psycopg.Error):
        load(con, "actual_daily", df)


def test_load_rejects_unknown_table(con):
    """Fails if an arbitrary table name reaches SQL (identifier allowlist)."""
    with pytest.raises(ValueError):
        load(con, "raw_actual_daily; drop table x", actual("c", []))


def test_published_daily_uses_full_days_only(con):
    """Fails if a day with 23 of 24 hours is kept, or max/min are computed wrongly."""
    load(con, "published_hourly", hourly("c", "2025-01-01", 1, DAY1_TEMPS))
    load(con, "published_hourly", hourly("c", "2025-01-02", 1, [25.0] * 23))
    build_models(con)
    rows = con.execute(
        "select date, lead_days, tmax_c, tmin_c from stg_published_daily order by date"
    ).fetchall()
    assert rows == [(pd.Timestamp("2025-01-01").date(), 1, 31.0, 18.0)]


def test_forecast_error_sign_is_forecast_minus_actual(con):
    """Fails if the error sign flips (a too-warm forecast must be positive)."""
    load(con, "published_hourly", hourly("c", "2025-01-01", 1, DAY1_TEMPS))
    load(con, "actual_daily", actual("c", [("2025-01-01", 29.0, 19.0)]))
    build_models(con)
    rows = con.execute(
        "select variable, forecast_c, actual_c, error_c from mart_forecast_error order by variable"
    ).fetchall()
    assert rows == [("tmax", 31.0, 29.0, 2.0), ("tmin", 18.0, 19.0, -1.0)]


def test_forecast_error_excludes_days_without_actuals(con):
    """Fails if the join turns into a left join and emits rows with null actuals."""
    load(con, "published_hourly", hourly("c", "2025-01-01", 1, DAY1_TEMPS))
    load(con, "published_hourly", hourly("c", "2025-01-05", 1, DAY1_TEMPS))
    load(con, "actual_daily", actual("c", [("2025-01-01", 29.0, 19.0)]))
    build_models(con)
    n = con.execute("select count(*) from mart_forecast_error where variable = 'tmax'").fetchall()[
        0
    ]
    assert n == (1,)


def test_error_by_lead_metrics_hand_computed(con):
    """Fails if bias, MAE, share-off-by-3C or worst miss are aggregated wrongly.

    Lead 1 tmax errors: +2 (31 vs 29) and -4 (31 vs 35) -> bias -1, MAE 3,
    off by >=3C on 1 of 2 days, worst miss 4.
    """
    load(con, "published_hourly", hourly("c", "2025-01-01", 1, DAY1_TEMPS))
    load(con, "published_hourly", hourly("c", "2025-01-02", 1, DAY1_TEMPS))
    load(con, "actual_daily", actual("c", [("2025-01-01", 29.0, 18.0), ("2025-01-02", 35.0, 18.0)]))
    build_models(con)
    row = con.execute(
        "select n_days, bias_c, mae_c, share_off_2c, share_off_3c, max_abs_error_c "
        "from mart_error_by_lead where variable = 'tmax' and lead_days = 1"
    ).fetchall()[0]
    assert row == (2, -1.0, 3.0, 1.0, 0.5, 4.0)


def test_snapshot_reports_schema_count_and_sample(con):
    """Fails if the results-page snapshot loses the row count or column types."""
    load(con, "actual_daily", actual("c", [("2025-01-01", 29.0, 19.0)]))
    snap = snapshot(con, "raw_actual_daily", n=5)
    assert snap["table"] == "raw_actual_daily"
    assert snap["row_count"] == 1
    assert ("tmax_c", "double precision") in [tuple(c) for c in snap["columns"]]
    assert len(snap["sample"]) == 1
