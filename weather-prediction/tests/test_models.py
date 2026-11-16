"""Models: seasonal climatology, anomaly decay, per-lead bias correction, intervals, outlook."""

import numpy as np
import pandas as pd
import pytest

from weatherwise.models import (
    Climatology,
    LeadCorrector,
    assemble_outlook,
    fit_anomaly_decay,
    interval_coverage,
    seasonal_features,
    split_by_date,
)


def test_seasonal_features_shape_and_quarter_turn():
    """Fails if the feature count changes or day 91 is not a quarter of the year (sin ~ 1)."""
    f = seasonal_features(pd.to_datetime(["2025-04-01", "2025-01-01", "2026-01-01"]))
    assert f.shape == (3, 4)
    assert f[0, 0] > 0.999


def test_climatology_recovers_season_and_trend():
    """Fails if the trend term is missing: 0.5 C/year must be extrapolated to unseen years."""
    dates = pd.date_range("2010-01-01", "2019-12-31", freq="D")
    years = (dates - pd.Timestamp("2010-01-01")).days / 365.25
    values = 25 + 3 * seasonal_features(dates)[:, 0] + 0.5 * years
    clim = Climatology().fit(dates, values)
    future = pd.to_datetime(["2022-04-01"])
    # by hand: 2022-04-01 is 4473 days = 12.2464 years after the start; day 91 -> sin 0.99998
    expected = 25 + 3 * 0.99998 + 0.5 * 12.2464
    assert clim.predict(future)[0] == pytest.approx(expected, abs=0.05)


def test_anomaly_decay_learns_geometric_ratio():
    """Fails if the decay is fitted on the wrong lag: halving each day gives 0.5, 0.25."""
    anom = pd.Series([16, 8, 4, 2, 1, 0.5, 0.25, 0.125], dtype=float)
    coef = fit_anomaly_decay(anom, max_lead=2, window=1)
    assert coef == pytest.approx([0.5, 0.25])


def test_split_by_date_is_strict():
    """Fails if a row on the test start date leaks into training."""
    df = pd.DataFrame({"date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"])})
    train, test = split_by_date(df, pd.Timestamp("2025-01-02"))
    assert train["date"].tolist() == [pd.Timestamp("2025-01-01")]
    assert test["date"].tolist() == [pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03")]


def test_interval_coverage_inclusive_bounds():
    """Fails if a value exactly on a bound is counted as outside."""
    assert interval_coverage(np.array([1, 2, 3, 4]), np.zeros(4), np.full(4, 2)) == 0.5


def synthetic_pairs(n: int, bias: float, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-01", periods=n, freq="D")
    act = 28 + 3 * seasonal_features(dates)[:, 0] + rng.normal(0, 1, n)
    rows = []
    for lead in (1, 2):
        fc = act + bias + rng.uniform(-1, 1, n)
        rows.append(
            pd.DataFrame({"date": dates, "lead_days": lead, "forecast_c": fc, "actual_c": act})
        )
    return pd.concat(rows, ignore_index=True)


def test_corrector_removes_constant_warm_bias():
    """Fails if a +2 C forecast bias survives correction (raw MAE 2, corrected must be < 0.7)."""
    train = synthetic_pairs(800, bias=2.0, seed=1)
    test = synthetic_pairs(300, bias=2.0, seed=2)
    model = LeadCorrector().fit(train)
    out = model.predict(test)
    raw_mae = (test["forecast_c"] - test["actual_c"]).abs().mean()
    cor_mae = (out["pred_c"] - test["actual_c"]).abs().mean()
    assert raw_mae > 1.9
    assert cor_mae < 0.7
    assert model.method[1] != "raw"


def test_corrector_keeps_raw_when_forecast_is_unbiased():
    """Fails if a correction that wins validation by noise alone replaces the raw forecast.

    actual = forecast + independent noise, so the forecast is already the best guess and no
    candidate can beat raw by the 2% margin; picking linear or gbm here is overfitting.
    """
    rng = np.random.default_rng(3)
    dates = pd.date_range("2022-01-01", periods=800, freq="D")
    fc = 28 + 3 * seasonal_features(dates)[:, 0] + rng.normal(0, 1, 800)
    train = pd.concat(
        [
            pd.DataFrame(
                {
                    "date": dates,
                    "lead_days": lead,
                    "forecast_c": fc,
                    "actual_c": fc + rng.uniform(-1, 1, 800),
                }
            )
            for lead in (1, 2)
        ],
        ignore_index=True,
    )
    model = LeadCorrector(min_gain=0.02).fit(train)
    assert model.method == {1: "raw", 2: "raw"}


def test_corrector_intervals_cover_about_80_percent():
    """Fails if the p10-p90 band is too narrow or too wide on fresh data (0.72-0.88)."""
    train = synthetic_pairs(1500, bias=1.0, seed=4)
    test = synthetic_pairs(1000, bias=1.0, seed=5)
    out = LeadCorrector().fit(train).predict(test)
    cov = interval_coverage(
        test["actual_c"].to_numpy(), out["lo_c"].to_numpy(), out["hi_c"].to_numpy()
    )
    assert 0.72 <= cov <= 0.88
    assert (out["lo_c"] <= out["pred_c"]).all() and (out["pred_c"] <= out["hi_c"]).all()


def test_corrector_rejects_unseen_lead():
    """Fails if a lead with no trained model is silently predicted."""
    model = LeadCorrector().fit(synthetic_pairs(400, bias=0.0, seed=6))
    bad = synthetic_pairs(10, bias=0.0, seed=7).assign(lead_days=9)
    with pytest.raises(ValueError, match="lead"):
        model.predict(bad)


class ConstCorrector:
    """Stand-in short-range model: adds 1 C, band +/-2."""

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        p = df["forecast_c"].to_numpy() + 1
        return pd.DataFrame({"pred_c": p, "lo_c": p - 2, "hi_c": p + 2})


class FlatClimatology:
    def predict(self, dates) -> np.ndarray:
        return np.full(len(dates), 25.0)


def test_outlook_blends_short_and_long_range():
    """Fails if leads 1-7 do not use the corrected forecast or 8-30 do not use clim + decay.

    Lead 1: forecast 30 -> 31. Lead 8: clim 25 + coef 0.5 * anomaly 2 -> 26.
    """
    today = pd.Timestamp("2026-11-14")
    live = pd.DataFrame(
        {
            "date": pd.date_range(today + pd.Timedelta(days=1), periods=16, freq="D"),
            "forecast_c": 30.0,
        }
    )
    coef = np.full(30, 0.5)
    resid_q = {lead: (-3.0, 3.0) for lead in range(1, 31)}
    out = assemble_outlook(
        today,
        live,
        ConstCorrector(),
        FlatClimatology(),
        coef,
        recent_anomaly=2.0,
        long_quantiles=resid_q,
        short_leads=7,
        horizon=30,
    )
    assert len(out) == 30
    assert out["lead_days"].tolist() == list(range(1, 31))
    assert out.loc[0, "pred_c"] == 31.0 and out.loc[0, "source"] == "corrected forecast"
    assert out.loc[7, "pred_c"] == 26.0 and out.loc[7, "source"] == "climatology + anomaly"
    assert out.loc[7, "lo_c"] == 23.0 and out.loc[7, "hi_c"] == 29.0
    assert out.loc[7, "raw_forecast_c"] == 30.0  # raw NWP still shown for leads 8-16
    assert pd.isna(out.loc[20, "raw_forecast_c"])


def test_long_range_backtest_hand_computed():
    """Fails if the anomaly is taken at the wrong origin or leads are misaligned.

    Flat climatology 25. Origin day 1 has anomaly +2 (actual 27).
    Lead 1: 25 + 0.5 * 2 = 26. Lead 2: 25 + 0.25 * 2 = 25.5. Persistence repeats 27.
    """
    from weatherwise.models import long_range_backtest, residual_quantiles

    dates = pd.date_range("2025-01-01", periods=4, freq="D")
    actual = pd.Series([25.0, 27.0, 26.0, 25.0], index=dates)
    bt = long_range_backtest(
        actual, FlatClimatology(), np.array([0.5, 0.25]), origins=[dates[1]], window=1
    )
    assert bt["lead_days"].tolist() == [1, 2]
    assert bt["pred_c"].tolist() == [26.0, 25.5]
    assert bt["clim_c"].tolist() == [25.0, 25.0]
    assert bt["persist_c"].tolist() == [27.0, 27.0]
    assert bt["actual_c"].tolist() == [26.0, 25.0]
    q = residual_quantiles(bt, (0.1, 0.9))
    assert q[1] == (0.0, 0.0)  # residual 26 - 26
    assert q[2] == (-0.5, -0.5)  # residual 25 - 25.5


def test_corrector_band_reflects_most_recent_year():
    """Fails if the p10-p90 band is built from stale years when forecast error has shrunk.

    8 years of history: error U(-3, 3) until the last 364 days, then U(-0.5, 0.5). The band
    must follow the recent regime: about -0.4 / +0.4. A band from the last 25% of history
    (2 years) mixes in the old regime and comes out near +/-2.
    """
    n, recent = 2920, 364
    rng = np.random.default_rng(8)
    dates = pd.date_range("2018-01-01", periods=n, freq="D")
    fc = 28 + 3 * seasonal_features(dates)[:, 0] + rng.normal(0, 1, n)
    noise = np.where(np.arange(n) < n - recent, rng.uniform(-3, 3, n), rng.uniform(-0.5, 0.5, n))
    train = pd.DataFrame({"date": dates, "lead_days": 1, "forecast_c": fc, "actual_c": fc + noise})
    lo, hi = LeadCorrector().fit(train).band[1]
    assert -0.6 < lo < -0.2 and 0.2 < hi < 0.6
