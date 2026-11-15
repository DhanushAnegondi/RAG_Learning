"""Tests added after the sprint-01 ponytail reviews. Each closes a named review finding."""

import json
from datetime import date

import duckdb
import numpy as np
import pandas as pd
import pytest
import requests

from weatherwise import ingest, models, pipeline, warehouse
from weatherwise.config import City
from weatherwise.report import build_page

CITY = City("testville", 12.0, 77.0, "Asia/Kolkata")


class Resp:
    def __init__(self, status: int, body: dict | None = None, bad_json: bool = False) -> None:
        self.status_code, self._body, self._bad = status, body or {}, bad_json

    def json(self) -> dict:
        if self._bad:
            raise requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0)
        return self._body


class Router:
    """Fake session: answers by URL, records every call."""

    def __init__(self, answer) -> None:
        self.answer, self.calls = answer, []

    def get(self, url: str, params: dict, timeout: float) -> Resp:
        self.calls.append({"url": url, "params": dict(params)})
        return self.answer(url, params)


# --- code review 1 / test review 1, 8: HTTP boundary -------------------------------------


def test_fetch_json_retries_gateway_error_with_html_body():
    """Fails if a 502 with a non-JSON body escapes as JSONDecodeError instead of a retry."""
    seq = iter([Resp(502, bad_json=True), Resp(200, {"ok": 1})])
    s = Router(lambda u, p: next(seq))
    assert ingest.fetch_json(s, "https://x", {}, sleep=lambda t: None) == {"ok": 1}
    assert len(s.calls) == 2


def test_fetch_json_retries_429_with_exponential_backoff():
    """Fails if rate limiting (429) is not retried or the first backoff is not 1 second."""
    seq = iter([Resp(429, {"reason": "slow down"}), Resp(200, {"ok": 1})])
    sleeps: list[float] = []
    ingest.fetch_json(Router(lambda u, p: next(seq)), "https://x", {}, sleep=sleeps.append)
    assert sleeps == [1]


# --- test review 3: request parameters (timezone makes daily buckets local) --------------


def test_fetchers_send_location_timezone_and_variables():
    """Fails if timezone, lead variable names or forecast_days are dropped from requests."""
    daily = {
        "daily": {
            "time": [],
            "temperature_2m_max": [],
            "temperature_2m_min": [],
            "precipitation_sum": [],
        }
    }
    hourly = {"hourly": {"time": [], **{f"temperature_2m_previous_day{n}": [] for n in (1, 2)}}}
    s = Router(lambda u, p: Resp(200, hourly if "previous" in u else daily))
    ingest.fetch_actuals(s, CITY, "2025-01-01", "2025-01-31")
    ingest.fetch_published(s, CITY, "2025-01-01", "2025-01-31", leads=[1, 2])
    ingest.fetch_live_forecast(s, CITY)
    a, p, f = s.calls
    for call in s.calls:
        assert call["params"]["timezone"] == "Asia/Kolkata"
        assert call["params"]["latitude"] == 12.0
    assert a["url"] == ingest.ARCHIVE_URL and a["params"]["end_date"] == "2025-01-31"
    assert p["params"]["hourly"] == "temperature_2m_previous_day1,temperature_2m_previous_day2"
    assert f["url"] == ingest.FORECAST_URL and f["params"]["forecast_days"] == 16
    assert "temperature_2m_max" in f["params"]["daily"]


# --- test review 2: fetch_all year loop -------------------------------------------------


def empty_answer(url: str, params: dict) -> Resp:
    if "previous" in url:
        return Resp(
            200,
            {
                "hourly": {
                    "time": [],
                    **{f"temperature_2m_previous_day{n}": [] for n in range(1, 8)},
                }
            },
        )
    return Resp(
        200,
        {
            "daily": {
                "time": [],
                "temperature_2m_max": [],
                "temperature_2m_min": [],
                "precipitation_sum": [],
            }
        },
    )


def test_fetch_all_on_new_years_day_never_requests_an_inverted_range():
    """Fails if on 1 January the loop asks for 2027-01-01..2026-12-31 (API answers 400)."""
    s = Router(empty_answer)
    con = warehouse.connect(":memory:")
    pipeline.fetch_all(con, CITY, "2020-01-01", "2026-06-01", date(2027, 1, 1), session=s)
    pub = [c["params"] for c in s.calls if "previous" in c["url"]]
    assert [(c["start_date"], c["end_date"]) for c in pub] == [("2026-06-01", "2026-12-31")]


# --- test review 4, 11: SQL grain and columns -------------------------------------------


def hourly(city: str, day: str, lead: int, temps: list[float]) -> pd.DataFrame:
    start = pd.Timestamp(day)
    return pd.DataFrame(
        {
            "city": city,
            "lead_days": lead,
            "temp_c": temps,
            "ts_local": [start + pd.Timedelta(hours=h) for h in range(len(temps))],
        }
    )


def actual(city: str, day: str, mx: float | None, mn: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "city": [city],
            "date": [pd.Timestamp(day)],
            "tmax_c": [mx],
            "tmin_c": [mn],
            "precip_mm": [0.0],
        }
    )


def test_sql_keeps_cities_and_leads_apart():
    """Fails if a group by or join drops city or lead_days and mixes their errors.

    Day 2025-01-01, actual max 30 in both cities.
    city a: lead 1 flat 31 (error +1), lead 2 flat 33 (error +3). city b: lead 1 flat 26 (-4).
    """
    con = warehouse.connect(":memory:")
    for city, lead, t in (("a", 1, 31.0), ("a", 2, 33.0), ("b", 1, 26.0)):
        warehouse.load(con, "published_hourly", hourly(city, "2025-01-01", lead, [t] * 24))
    for city in ("a", "b"):
        warehouse.load(con, "actual_daily", actual(city, "2025-01-01", 30.0, 20.0))
    warehouse.build_models(con)
    rows = con.execute(
        "select city, lead_days, n_days, bias_c from mart_error_by_lead "
        "where variable = 'tmax' order by city, lead_days"
    ).fetchall()
    assert rows == [("a", 1, 1, 1.0), ("a", 2, 1, 3.0), ("b", 1, 1, -4.0)]


def test_error_by_lead_rmse_and_quantiles_hand_computed():
    """Fails if rmse or the p10/p90 error columns are computed wrongly.

    Errors over 5 days: -2, -1, 0, 1, 2 -> rmse sqrt(10/5) = 1.414,
    p10 = -2 + 0.4 * 1 = -1.6, p90 = 1.6 (linear interpolation).
    """
    con = warehouse.connect(":memory:")
    for i, err in enumerate([-2.0, -1.0, 0.0, 1.0, 2.0]):
        day = f"2025-01-0{i + 1}"
        warehouse.load(con, "published_hourly", hourly("a", day, 1, [30.0 + err] * 24))
        warehouse.load(con, "actual_daily", actual("a", day, 30.0, 20.0))
    warehouse.build_models(con)
    row = con.execute(
        "select rmse_c, p10_error_c, p90_error_c from mart_error_by_lead where variable = 'tmax'"
    ).fetchall()[0]
    assert row == (1.414, -1.6, 1.6)


def test_actual_with_null_max_is_dropped_end_to_end():
    """Fails if a parsed null max reaches the marts (staging null filter removed)."""
    con = warehouse.connect(":memory:")
    payload = {
        "daily": {
            "time": ["2025-01-01"],
            "temperature_2m_max": [None],
            "temperature_2m_min": [20.0],
            "precipitation_sum": [0.0],
        }
    }
    warehouse.load(con, "actual_daily", ingest.parse_daily(payload, "a"))
    warehouse.load(con, "published_hourly", hourly("a", "2025-01-01", 1, [30.0] * 24))
    warehouse.build_models(con)
    assert con.execute("select count(*) from stg_actual_daily").fetchall() == [(0,)]
    assert con.execute("select count(*) from mart_forecast_error").fetchall() == [(0,)]


# --- test review 7: every loader -------------------------------------------------------


def dup_frames() -> dict[str, pd.DataFrame]:
    h = hourly("a", "2025-01-01", 1, [30.0])
    live = actual("a", "2025-01-02", 30.0, 20.0).assign(issued_on=pd.Timestamp("2025-01-01"))
    return {
        "actual_daily": actual("a", "2025-01-01", 30.0, 20.0),
        "published_hourly": h,
        "live_forecast": live,
    }


@pytest.mark.parametrize("table", ["actual_daily", "published_hourly", "live_forecast"])
def test_every_loader_is_idempotent_and_rejects_duplicate_batches(table):
    """Fails if any loader duplicates on rerun or silently collapses duplicate keys."""
    con = warehouse.connect(":memory:")
    df = dup_frames()[table]
    assert warehouse.load(con, table, df) == 1
    assert warehouse.load(con, table, df) == 1
    with pytest.raises(duckdb.Error):
        warehouse.load(con, table, pd.concat([df, df], ignore_index=True))


def test_live_forecasts_from_different_issue_days_both_survive():
    """Fails if issued_on drops out of the key and a new forecast overwrites yesterday's."""
    con = warehouse.connect(":memory:")
    base = actual("a", "2025-01-05", 30.0, 20.0)
    warehouse.load(con, "live_forecast", base.assign(issued_on=pd.Timestamp("2025-01-01")))
    n = warehouse.load(con, "live_forecast", base.assign(issued_on=pd.Timestamp("2025-01-02")))
    assert n == 2


def test_snapshot_rejects_unknown_table():
    """Fails if snapshot formats an unchecked table name into SQL."""
    with pytest.raises(ValueError):
        warehouse.snapshot(warehouse.connect(":memory:"), "nope; drop table x")


# --- code review 3, 4 / test review 5: outlook guards and seams --------------------------


class PlusOne:
    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        p = df["forecast_c"].to_numpy() + 1
        return pd.DataFrame({"pred_c": p, "lo_c": p - 2, "hi_c": p + 3})


class Flat25:
    def predict(self, dates) -> np.ndarray:
        return np.full(len(dates), 25.0)


TODAY = pd.Timestamp("2026-11-14")


def outlook(live_days: int, today: pd.Timestamp = TODAY) -> pd.DataFrame:
    live = pd.DataFrame(
        {"date": pd.date_range(today + pd.Timedelta(days=1), periods=live_days), "forecast_c": 30.0}
    )
    coef = 0.5 - 0.01 * np.arange(30)
    q = {n: (-1.0 - n / 10, 1.0 + n / 10) for n in range(1, 31)}
    return models.assemble_outlook(
        today,
        live,
        PlusOne(),
        Flat25(),
        coef,
        recent_anomaly=2.0,
        long_quantiles=q,
        short_leads=7,
        horizon=30,
    )


def test_outlook_seam_between_day_7_and_day_8():
    """Fails if lead 7 is not corrected, lead 8 uses the wrong decay or quantile, or bands drop.

    Lead 1 and 7: forecast 30 + 1 = 31, band 29 / 34.
    Lead 8: 25 + coef[7] * 2 = 25 + 0.43 * 2 = 25.86; band 25.86 - 1.8 / + 1.8.
    """
    out = outlook(16)
    for i in (0, 6):
        assert out.loc[i, ["pred_c", "lo_c", "hi_c"]].tolist() == [31.0, 29.0, 34.0]
        assert out.loc[i, "source"] == "corrected forecast"
    assert out.loc[7, "pred_c"] == pytest.approx(25.86)
    assert out.loc[7, "lo_c"] == pytest.approx(24.06)
    assert out.loc[7, "hi_c"] == pytest.approx(27.66)


@pytest.mark.parametrize("live_days", [0, 2])
def test_outlook_refuses_missing_published_forecast(live_days):
    """Fails if missing published days silently turn the week into climatology."""
    with pytest.raises(ValueError, match="published forecast"):
        outlook(live_days)


def test_recent_anomaly_uses_contiguous_window_and_checks_age():
    """Fails if the anomaly is stale, skips a gap, or averages the wrong days."""
    days = pd.date_range("2026-11-08", "2026-11-13")
    anom = pd.Series([9.0, 9.0, 9.0, 1.0, 2.0, 3.0], index=days)
    assert models.recent_anomaly(anom, pd.Timestamp("2026-11-14"), window=3) == 2.0
    with pytest.raises(ValueError, match="days old"):
        models.recent_anomaly(anom, pd.Timestamp("2026-11-19"), window=3)
    gappy = anom.copy()
    gappy.iloc[-2] = np.nan
    with pytest.raises(ValueError, match="gap"):
        models.recent_anomaly(gappy, pd.Timestamp("2026-11-14"), window=3)


# --- test review 9, 10: corrector and long-range edge cases -----------------------------


def test_corrector_with_too_little_history_fails_loudly():
    """Fails if 60 days of history silently produce an untested model."""
    dates = pd.date_range("2025-01-01", periods=60)
    df = pd.DataFrame({"date": dates, "lead_days": 1, "forecast_c": 30.0, "actual_c": 30.0})
    with pytest.raises(ValueError, match="history"):
        models.LeadCorrector().fit(df)


def test_corrector_band_always_contains_prediction():
    """Fails if one-signed residuals give a band that excludes the prediction (clamp removed).

    Actual is always 0.5 above a perfectly seasonal forecast, plus tiny noise, and raw is kept
    (min_gain=1 forbids corrections): residuals are all positive, so lo must clamp to 0.
    """
    rng = np.random.default_rng(9)
    dates = pd.date_range("2022-01-01", periods=600)
    fc = 28 + 3 * models.seasonal_features(dates)[:, 0]
    df = pd.DataFrame(
        {
            "date": dates,
            "lead_days": 1,
            "forecast_c": fc,
            "actual_c": fc + 0.5 + rng.uniform(0, 0.1, 600),
        }
    )
    m = models.LeadCorrector(min_gain=1.0).fit(df)
    assert m.method[1] == "raw"
    assert m.band[1][0] == 0.0 and m.band[1][1] > 0.5


def test_anomaly_decay_with_three_day_window_hand_computed():
    """Fails if the window is centred or allows partial windows.

    anom = 3, 0, 3, 3, 3, 0. x(t) = mean of the 3 days ending at t: NaN, NaN, 2, 2, 3, 2.
    Lead 1 pairs (x, y): (2, 3), (2, 3), (3, 0) -> sum xy 12, sum xx 17 -> 12/17.
    Partial windows would add (3, 0) and (1.5, 3) and give 16.5 / 28.25 instead.
    """
    anom = pd.Series([3.0, 0.0, 3.0, 3.0, 3.0, 0.0])
    assert models.fit_anomaly_decay(anom, max_lead=1, window=3)[0] == pytest.approx(12 / 17)


def test_residual_quantiles_on_ten_residuals():
    """Fails if the requested quantiles are ignored.

    Residuals 1..10 at lead 1: p10 = 1 + 0.9 * 1 = 1.9, p90 = 9.1 (linear interpolation).
    """
    bt = pd.DataFrame({"lead_days": 1, "actual_c": np.arange(1.0, 11.0), "pred_c": 0.0})
    assert models.residual_quantiles(bt, (0.1, 0.9))[1] == pytest.approx((1.9, 9.1))


# --- test review 6 / code review 5: leakage and out-of-sample bands ----------------------


def seasonal_actual(step_after: pd.Timestamp | None) -> pd.Series:
    rng = np.random.default_rng(10)
    idx = pd.date_range("2019-01-01", "2022-12-31")
    s = pd.Series(
        27 + 3 * models.seasonal_features(idx)[:, 0] + rng.normal(0, 1, len(idx)), index=idx
    )
    if step_after is not None:
        s[s.index >= step_after] += 10
    return s


def test_evaluate_long_never_learns_from_the_test_window():
    """Fails if climatology, decay or bands see test-window data (a +10 C jump there)."""
    t0 = pd.Timestamp("2022-06-01")
    _, clim_a, coef_a, bands_a = pipeline.evaluate_long(seasonal_actual(None), t0)
    _, clim_b, coef_b, bands_b = pipeline.evaluate_long(seasonal_actual(t0), t0)
    probe = pd.date_range("2023-01-01", periods=5)
    assert np.allclose(clim_a.predict(probe), clim_b.predict(probe))
    assert np.allclose(coef_a, coef_b)
    assert bands_a == bands_b


def test_evaluate_short_never_learns_from_the_test_window():
    """Fails if the corrector's chosen method or band changes when only test actuals change."""
    t0 = pd.Timestamp("2022-06-01")
    act = seasonal_actual(None)
    rng = np.random.default_rng(11)
    pairs = pd.concat(
        [
            pd.DataFrame(
                {
                    "date": act.index,
                    "lead_days": n,
                    "forecast_c": act.to_numpy() + 1 + rng.normal(0, 0.5, len(act)),
                    "actual_c": act.to_numpy(),
                }
            )
            for n in (1, 2)
        ],
        ignore_index=True,
    )
    shifted = pairs.copy()
    shifted.loc[shifted["date"] >= t0, "actual_c"] += 10
    clim = models.Climatology().fit(act.index, act.to_numpy())
    a, _ = pipeline.evaluate_short(pairs, act, clim, t0)
    b, _ = pipeline.evaluate_short(shifted, act, clim, t0)
    cols = ["chosen_method", "band_p10_p90_c"]
    assert a[cols].equals(b[cols])


def test_long_range_bands_are_out_of_sample():
    """Fails if bands come from residuals of the same rows the climatology was fit on.

    Out-of-sample calibration fits on all but the last year and measures that year, so the
    band must differ from the in-sample one built on the same final year.
    """
    act = seasonal_actual(None)
    oos = pipeline.calibrate_bands(act)
    clim = models.Climatology().fit(act.index, act.to_numpy())
    coef = models.fit_anomaly_decay(
        act - clim.predict(act.index), pipeline.HORIZON, pipeline.WINDOW
    )
    insample = models.residual_quantiles(
        models.long_range_backtest(
            act, clim, coef, act.index[-365 : -pipeline.HORIZON], pipeline.WINDOW
        )
    )
    assert set(oos) == set(range(1, pipeline.HORIZON + 1))
    assert oos != insample


# --- code review 1, 2, 7: findings and captions built from the measured tables ------------


def test_short_range_findings_report_kept_raw_and_worst_lead():
    """Fails if findings claim a correction where raw was kept, or hide the worst regression."""
    ev = pd.DataFrame(
        {
            "lead_days": [1, 2, 3],
            "published_mae_c": [0.7, 0.8, 0.9],
            "corrected_mae_c": [0.7, 0.7, 1.5],
            "improvement_pct": [0.0, 12.5, -66.7],
            "chosen_method": ["raw", "linear", "linear"],
            "band_coverage_pct": [72.0, 81.0, 60.0],
        }
    )
    text = pipeline.short_range_finding("max temp", ev)
    assert "kept the published forecast at lead 1" in text
    assert "lead 3" in text and "-66.7%" in text
    assert "60.0" in text and "81.0" in text


# --- test review 12, 13, 16: report and vacuous asserts ---------------------------------


def make_sprint(root, name: str, findings: list[str]) -> None:
    d = root / name
    (d / "metrics").mkdir(parents=True)
    (d / "meta.json").write_text(
        json.dumps({"title": name, "goal": "g", "findings": findings}), encoding="utf-8"
    )


def test_report_orders_sprint_10_above_sprint_9(tmp_path):
    """Fails if sprints sort as text, putting sprint-9 above sprint-10."""
    make_sprint(tmp_path, "sprint-9", ["zq-nine-zq"])
    make_sprint(tmp_path, "sprint-10", ["zq-ten-zq"])
    html = build_page(tmp_path)
    assert html.index("zq-ten-zq") < html.index("zq-nine-zq")


def test_report_escapes_findings_and_csv_cells_and_embeds_charts(tmp_path):
    """Fails if findings or CSV cells inject HTML, or charts are not embedded."""
    make_sprint(tmp_path, "sprint-01", ["<b>bold</b>"])
    d = tmp_path / "sprint-01"
    (d / "metrics" / "01_t.csv").write_text("a,b\n<i>x</i>,2\n", encoding="utf-8")
    (d / "charts").mkdir()
    (d / "charts" / "c.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    html = build_page(tmp_path)
    assert "<b>bold</b>" not in html and "&lt;b&gt;bold&lt;/b&gt;" in html
    assert "<i>x</i>" not in html and "&lt;i&gt;x&lt;/i&gt;" in html
    assert "data:image/png;base64,iVBORw0KGgo" in html


def test_seasonal_features_hand_values():
    """Fails if the yearly period or harmonic order is wrong (values computed by hand).

    1 April 2025 is day 91: w = 2 pi 91 / 365.25 = 1.5654 rad -> sin 0.99998, cos 0.0054,
    sin 2w = 0.0108, cos 2w = -0.99994.
    """
    f = models.seasonal_features(pd.to_datetime(["2025-04-01"]))[0]
    assert f == pytest.approx([0.99998, 0.0054, 0.0108, -0.99994], abs=2e-4)


def test_share_off_counts_an_error_of_exactly_3c():
    """Fails if 'off by 3 C or more' excludes an error of exactly 3 C (>= became >).

    Errors +3 and +1 -> share_off_3c 0.5, share_off_2c 0.5.
    """
    con = warehouse.connect(":memory:")
    for day, fc in (("2025-01-01", 33.0), ("2025-01-02", 31.0)):
        warehouse.load(con, "published_hourly", hourly("a", day, 1, [fc] * 24))
        warehouse.load(con, "actual_daily", actual("a", day, 30.0, 20.0))
    warehouse.build_models(con)
    row = con.execute(
        "select share_off_2c, share_off_3c from mart_error_by_lead where variable = 'tmax'"
    ).fetchall()[0]
    assert row == (0.5, 0.5)
