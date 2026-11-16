"""Sprint 02 models: drift tracking, multi-model blend, LSTM, long-range selection, log rows."""

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from weatherwise import deep, models, pipeline
from weatherwise.config import City


def pairs(n: int, lead: int, forecast, actual, start="2023-01-01", **extra) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range(start, periods=n, freq="D"),
            "lead_days": lead,
            "forecast_c": forecast,
            "actual_c": actual,
            **extra,
        }
    )


def test_recent_bias_equals_a_constant_error():
    """Fails if the recent-bias feature has the wrong sign or scale: forecasts always 2 C too
    warm must give bias_recent = +2 once there is a week of history."""
    df = models.add_recent_bias(pairs(40, 1, 27.0, 25.0))
    assert df["bias_recent"].iloc[:8].isna().all()  # 7 errors needed, then known 2 days later
    assert np.allclose(df["bias_recent"].iloc[9:], 2.0)


def test_recent_bias_only_uses_errors_known_when_the_forecast_was_issued():
    """Fails if the feature peeks at errors the forecaster could not have seen.

    A lead-2 forecast for day D is issued on D-2, when the newest verified lead-2 error is for
    D-3. So changing the actual on day k may change bias_recent from day k+3 on, never earlier.
    """
    base = pairs(60, 2, 27.0, 25.0)
    spiked = base.copy()
    spiked.loc[30, "actual_c"] = 15.0
    a = models.add_recent_bias(base)["bias_recent"]
    b = models.add_recent_bias(spiked)["bias_recent"]
    assert a.iloc[:33].equals(b.iloc[:33])
    assert a.iloc[33] != b.iloc[33]


def test_drift_candidate_subtracts_the_recent_bias():
    """Fails if drift adds the bias instead of removing it. forecast 27, bias +2 -> 25."""
    df = pairs(3, 1, 27.0, 25.0, bias_recent=[2.0, np.nan, -1.0])
    got = models._fit_candidate("drift", df)(df)
    assert got.tolist() == [25.0, 27.0, 28.0]


def test_ens_mean_averages_the_models_that_exist():
    """Fails if a missing model is counted as zero. (30 + 32) / 2 = 31; (30 + 32 + 34) / 3 = 32."""
    df = pairs(
        2, 1, 30.0, 0.0, fc_gfs=[32.0, 32.0], fc_ecmwf=[np.nan, 34.0], fc_gem=[np.nan, np.nan]
    )
    got = models._fit_candidate("ens_mean", df)(df)
    assert got.tolist() == [31.0, 32.0]


def flipping_bias(n: int, seed: int) -> pd.DataFrame:
    """Forecast bias flips between +2 and -2 every 200 days: no fixed correction can fix it.
    Day-to-day weather noise (sd 3) hides the bias from anything that only sees the forecast."""
    rng = np.random.default_rng(seed)
    days = np.arange(n)
    actual = 25 + 5 * np.sin(2 * np.pi * days / 365.25) + rng.normal(0, 3.0, n)
    bias = np.where((days // 200) % 2 == 0, 2.0, -2.0)
    return pairs(n, 1, actual + bias + rng.normal(0, 0.3, n), actual, start="2022-01-01")


def test_corrector_picks_drift_when_the_bias_keeps_changing():
    """Fails if a drifting bias is not tracked: drift must be chosen and beat raw by half."""
    df = models.add_recent_bias(flipping_bias(1400, seed=3))
    corr = models.LeadCorrector().fit(df.iloc[:1200])
    assert corr.method[1] == "drift"
    test = df.iloc[1200:]
    pred = corr.predict(test)["pred_c"]
    mae_cor = (pred - test["actual_c"]).abs().mean()
    mae_raw = (test["forecast_c"] - test["actual_c"]).abs().mean()
    assert mae_cor < 0.5 * mae_raw


def test_corrector_picks_blend_when_another_model_is_sharper():
    """Fails if the extra weather models are ignored: published is noisy (sd 2), gfs is sharp
    (sd 0.3) but 1.5 C too warm, so the plain mean is not enough and blend must win."""
    rng = np.random.default_rng(5)
    n = 1400
    days = np.arange(n)
    actual = 25 + 5 * np.sin(2 * np.pi * days / 365.25) + rng.normal(0, 0.5, n)
    df = pairs(
        n,
        1,
        actual + rng.normal(0, 2.0, n),
        actual,
        start="2022-01-01",
        fc_gfs=actual + 1.5 + rng.normal(0, 0.3, n),
        fc_ecmwf=np.nan,
        fc_gem=np.nan,
    )
    corr = models.LeadCorrector().fit(df.iloc[:1200])
    assert corr.method[1] == "blend"
    test = df.iloc[1200:]
    mae = (corr.predict(test)["pred_c"] - test["actual_c"]).abs().mean()
    assert mae < 0.6  # raw is about 1.6


def test_candidates_without_extra_columns_are_the_sprint_1_three():
    """Fails if drift or blend are offered when their inputs do not exist."""
    assert models.candidates(pairs(3, 1, 27.0, 25.0)) == ("raw", "linear", "gbm")
    full = pairs(3, 1, 27.0, 25.0, bias_recent=0.0, fc_gfs=1.0, fc_ecmwf=1.0, fc_gem=1.0)
    assert models.candidates(full) == ("raw", "linear", "gbm", "drift", "ens_mean", "blend")


def test_predict_all_scores_every_candidate_for_the_leaderboard():
    """Fails if the leaderboard would show only the winner."""
    df = models.add_recent_bias(flipping_bias(900, seed=1))
    corr = models.LeadCorrector().fit(df.iloc[:800])
    preds = corr.predict_all(df.iloc[800:])
    assert set(preds.columns) == {"raw", "linear", "gbm", "drift"}
    assert preds["raw"].tolist() == df["forecast_c"].iloc[800:].tolist()


def ar1(n: int, phi: float, seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + rng.normal(0, 1.0)
    return pd.Series(x, index=pd.date_range("2015-01-01", periods=n, freq="D"))


def test_lstm_learns_persistence_and_beats_predicting_zero():
    """Fails if the network does not train: on an AR(1) anomaly series (phi 0.9) the day-1
    forecast must beat 'anomaly = 0' (climatology) by a clear margin on unseen origins."""
    anom = ar1(1500, 0.9, seed=0)
    net = deep.AnomalyLSTM(lookback=14, horizon=5, hidden=16, epochs=30, seed=0).fit(anom[:1200])
    origins = anom.index[1200:1490]
    pred = net.predict(anom, origins)
    assert list(pred.columns) == ["origin", "lead_days", "anom_pred"]
    lead1 = pred[pred.lead_days == 1].set_index("origin")["anom_pred"]
    truth = anom.shift(-1).loc[lead1.index]
    assert (lead1 - truth).abs().mean() < 0.75 * truth.abs().mean()


def test_lstm_is_repeatable_and_refuses_too_little_history():
    """Fails if two runs with one seed disagree (results could not be reproduced), or a window
    with a gap is silently predicted."""
    anom = ar1(500, 0.8, seed=1)
    a = deep.AnomalyLSTM(lookback=14, horizon=3, hidden=8, epochs=3, seed=0).fit(anom[:400])
    b = deep.AnomalyLSTM(lookback=14, horizon=3, hidden=8, epochs=3, seed=0).fit(anom[:400])
    origin = [anom.index[450]]
    assert np.allclose(a.predict(anom, origin)["anom_pred"], b.predict(anom, origin)["anom_pred"])
    holed = anom.copy()
    holed.iloc[445] = np.nan
    assert a.predict(holed, origin).empty
    with pytest.raises(ValueError, match="history"):
        deep.AnomalyLSTM(lookback=14, horizon=3).fit(anom[:10])


def test_long_range_method_needs_a_clear_win_over_the_simple_model():
    """Fails if the LSTM replaces the simple model on a tie or a sliver (under 2%), or the best
    of several challengers is not the one picked."""
    assert pipeline.choose_long({"decay": 1.00, "lstm": 0.99}) == "decay"
    assert pipeline.choose_long({"decay": 1.00, "lstm": 0.97}) == "lstm"
    assert pipeline.choose_long({"decay": 1.00}) == "decay"
    assert pipeline.choose_long({"decay": 1.00, "lstm": 0.97, "mix": 0.95}) == "mix"


def test_adaptive_band_follows_recent_misses_and_never_peeks():
    """Fails if the range ignores a change in recent errors, or uses a miss the forecaster
    could not have known yet.

    Lead 1, window 10. Residuals (actual - forecast) are 0 until 20 Jan, then +4 from 21 Jan.
    A lead-1 forecast for day D is issued on D-1 and can know misses up to D-2.
    22 Jan: knows up to 20 Jan -> all zeros -> upper edge +0.
    23 Jan: knows 21 Jan -> nine 0s and one 4 -> p90 = 0.4 (linear interpolation).
    1 Feb: ten 4s -> lower and upper edge +4, lower clamped to 0 so the forecast stays inside.
    """
    days = pd.date_range("2025-01-01", "2025-02-05", freq="D")
    resid = pd.Series(np.where(days >= "2025-01-21", 4.0, 0.0), index=days)
    frame = pd.DataFrame({"date": days, "lead_days": 1, "pred_c": 20.0})
    band = models.adaptive_band(frame, {1: resid}, window=10, min_n=10).set_index(frame["date"])
    assert band.loc["2025-01-22", "hi_c"] == 20.0
    assert band.loc["2025-01-23", "hi_c"] == pytest.approx(20.4)
    assert band.loc["2025-02-01", ["lo_c", "hi_c"]].tolist() == [20.0, 24.0]


def test_adaptive_band_learns_from_new_outcomes_in_the_frame_and_falls_back():
    """Fails if outcomes that arrive after training are ignored, or a lead with too little
    history gets no range at all (falls back to the whole history's p10-p90)."""
    days = pd.date_range("2025-01-01", periods=30, freq="D")
    hist = pd.Series(0.0, index=days[:5])  # too short for the window
    frame = pd.DataFrame({"date": days[5:], "lead_days": 1, "pred_c": 20.0, "actual_c": 23.0})
    band = models.adaptive_band(frame, {1: hist}, window=10, min_n=10)
    assert band["hi_c"].iloc[0] == 20.0  # fallback: history is all zeros
    assert band["hi_c"].iloc[-1] == 23.0  # ten outcomes of +3 have been seen by then


def test_city_today_uses_the_city_clock_not_the_computer_clock():
    """Fails if 'today' comes from UTC or the laptop: at 05:00 UTC on 14 Nov it is still
    13 Nov in Torrance and already 14 Nov in Bengaluru."""
    now = datetime(2026, 11, 14, 5, 0, tzinfo=UTC)
    assert pipeline.city_today(City("x", 0, 0, "America/Los_Angeles"), now) == date(2026, 11, 13)
    assert pipeline.city_today(City("x", 0, 0, "Asia/Kolkata"), now) == date(2026, 11, 14)


def test_log_rows_record_the_issue_day_as_target_minus_lead():
    """Fails if a hindcast is filed under the wrong issue day or loses its range."""
    frame = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-11-14")],
            "lead_days": [3],
            "pred_c": [25.0],
            "lo_c": [23.0],
            "hi_c": [27.5],
            "published_c": [24.0],
            "method": ["drift"],
        }
    )
    row = pipeline.log_rows("t", "hindcast", "tmax", frame, pd.Timestamp("2026-11-14 09:00"))
    got = row.iloc[0].to_dict()
    assert got["issued_on"] == pd.Timestamp("2026-11-11")
    assert (got["city"], got["kind"], got["variable"], got["method"]) == (
        "t",
        "hindcast",
        "tmax",
        "drift",
    )
    assert (got["pred_c"], got["lo_c"], got["hi_c"], got["published_c"]) == (25.0, 23.0, 27.5, 24.0)


class NeedsGfs:
    """A corrector that only works if the other model's forecast reaches it."""

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        p = df["fc_gfs"].to_numpy(dtype=float)
        return pd.DataFrame({"pred_c": p, "lo_c": p - 1, "hi_c": p + 1}, index=df.index)


class Flat25:
    def predict(self, dates) -> np.ndarray:
        return np.full(len(dates), 25.0)


def test_outlook_passes_extra_model_columns_and_accepts_a_long_range_override():
    """Fails if days 1-7 lose the other models' forecasts, or an LSTM long-range forecast is
    ignored in favour of the default. Day 2 gfs = 31 -> pred 31; day 9 override = 20.5."""
    today = pd.Timestamp("2026-11-14")
    dates = pd.date_range(today + pd.Timedelta(days=1), periods=10, freq="D")
    live = pd.DataFrame({"date": dates, "forecast_c": 28.0, "fc_gfs": 30.0 + np.arange(10)})
    long_pred = 20.0 + np.arange(10) / 16
    out = models.assemble_outlook(
        today,
        live,
        NeedsGfs(),
        Flat25(),
        np.zeros(10),
        0.0,
        {n: (-1.0, 1.0) for n in range(1, 11)},
        short_leads=7,
        horizon=10,
        long_pred=long_pred,
    )
    assert out.loc[out.lead_days == 2, "pred_c"].item() == 31.0
    assert out.loc[out.lead_days == 9, "pred_c"].item() == 20.5
    assert out.loc[out.lead_days == 9, "lo_c"].item() == 19.5


def seasonal_actual(step_after: pd.Timestamp | None) -> pd.Series:
    rng = np.random.default_rng(10)
    idx = pd.date_range("2019-01-01", "2022-12-31")
    s = pd.Series(
        27 + 3 * models.seasonal_features(idx)[:, 0] + rng.normal(0, 1, len(idx)), index=idx
    )
    if step_after is not None:
        s[s.index >= step_after] += 10
    return s


def test_long_range_selection_and_range_never_see_the_test_window():
    """Fails if the long-range method choice or its starting misses change when only
    test-window data changes (a +10 C jump from the test start on)."""
    t0 = pd.Timestamp("2022-06-01")
    a = pipeline.evaluate_long_methods(seasonal_actual(None), t0, use_lstm=False)
    b = pipeline.evaluate_long_methods(seasonal_actual(t0), t0, use_lstm=False)
    assert a["val_mae"] == b["val_mae"]
    assert a["chosen"] == b["chosen"] == "decay"
    assert a["board"]["cv_mae_c"].tolist() == b["board"]["cv_mae_c"].tolist()
    assert a["board"]["test_mae_c"].tolist() != b["board"]["test_mae_c"].tolist()
