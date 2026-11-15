"""Forecast models.

Short range (leads 1-7): the published forecast, corrected per lead (model output statistics).
Candidates compete in rolling-origin CV; the band is the out-of-fold residual p10-p90.
  raw       the published forecast as is
  linear    fixed correction from forecast value and season
  gbm       gradient boosting on the same inputs
  drift     subtract the recent bias of the forecast (decaying average of errors already
            verified when the forecast was issued); follows the bias as upstream models change
  ens_mean  mean of the weather models available that day
  blend     gradient boosting on every model, their disagreement, and the recent bias

Long range (leads 8-30): no forecast model has day-level skill there, so: seasonal
climatology with a warming trend, plus today's anomaly decayed per lead by a learned factor.
The band is the backtest residual p10-p90 per lead.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression

YEAR_DAYS = 365.25
CANDIDATES = ("raw", "linear", "gbm")
MODEL_COLS = ("fc_gfs", "fc_ecmwf", "fc_gem")  # other weather models, beside forecast_c


def candidates(df: pd.DataFrame) -> tuple[str, ...]:
    """Candidate methods the columns of df can support."""
    out = list(CANDIDATES)
    if "bias_recent" in df.columns:
        out.append("drift")
    if any(c in df.columns for c in MODEL_COLS):
        out += ["ens_mean", "blend"]
    return tuple(out)


def add_recent_bias(
    pairs: pd.DataFrame, halflife: float = 14, min_periods: int = 7
) -> pd.DataFrame:
    """Adds bias_recent: decaying average of (forecast - actual) for the same lead, using only
    errors already verified when the forecast was issued.

    A lead-L forecast for day D is issued on D-L; the newest lead-L forecast with a known
    outcome then is the one for D-L-1, so the average is shifted L+1 days. Rows without an
    actual (future days) get the last known value.
    """
    out = pairs.copy()
    out["bias_recent"] = np.nan
    for lead, g in out.groupby("lead_days"):
        s = (g["forecast_c"] - g["actual_c"]).set_axis(pd.DatetimeIndex(g["date"]))
        daily = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D"))
        ew = daily.ewm(halflife=halflife, min_periods=min_periods).mean().shift(int(lead) + 1)
        out.loc[g.index, "bias_recent"] = ew.reindex(s.index).to_numpy()
    return out


def seasonal_features(dates) -> np.ndarray:
    """sin/cos of the annual cycle and its first harmonic, shape (n, 4)."""
    w = 2 * np.pi * pd.DatetimeIndex(dates).day_of_year.to_numpy() / YEAR_DAYS
    return np.column_stack([np.sin(w), np.cos(w), np.sin(2 * w), np.cos(2 * w)])


class Climatology:
    """Expected value for a calendar day: annual cycle plus a linear trend in years."""

    def fit(self, dates, values) -> "Climatology":
        self.ref = pd.DatetimeIndex(dates).min()
        self.model = LinearRegression().fit(self._x(dates), np.asarray(values, dtype=float))
        return self

    def _x(self, dates) -> np.ndarray:
        years = (pd.DatetimeIndex(dates) - self.ref).days.to_numpy() / YEAR_DAYS
        return np.column_stack([years, seasonal_features(dates)])

    def predict(self, dates) -> np.ndarray:
        return self.model.predict(self._x(dates))


def _recent_mean(anom: pd.Series, window: int) -> pd.Series:
    return anom.rolling(window, min_periods=window).mean()


def fit_anomaly_decay(anom: pd.Series, max_lead: int, window: int = 3) -> np.ndarray:
    """Per-lead factor c[l] in anomaly(t+l) ~ c[l] * mean(anomaly over the last `window` days).

    `anom` must be a contiguous daily series (gaps as NaN), so shift(-l) means l days.
    """
    x = _recent_mean(anom, window)
    coef = []
    for lead in range(1, max_lead + 1):
        y = anom.shift(-lead)
        ok = x.notna() & y.notna()
        coef.append(float((x[ok] * y[ok]).sum() / (x[ok] ** 2).sum()))
    return np.array(coef)


def split_by_date(df: pd.DataFrame, test_start: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    return df[df["date"] < test_start], df[df["date"] >= test_start]


def interval_coverage(actual, lo, hi) -> float:
    actual, lo, hi = (np.asarray(v, dtype=float) for v in (actual, lo, hi))
    return float(np.mean((actual >= lo) & (actual <= hi)))


def _features(df: pd.DataFrame) -> np.ndarray:
    return np.column_stack([df["forecast_c"].to_numpy(), seasonal_features(df["date"])])


def _model_matrix(df: pd.DataFrame) -> np.ndarray:
    """forecast_c and the other weather models, NaN where a model has no forecast."""
    cols = [df["forecast_c"].to_numpy(dtype=float)]
    cols += [
        df[c].to_numpy(dtype=float) if c in df.columns else np.full(len(df), np.nan)
        for c in MODEL_COLS
    ]
    return np.column_stack(cols)


def _blend_features(df: pd.DataFrame) -> np.ndarray:
    """Published forecast, how far each other model disagrees with it, recent bias, season.
    Disagreements (not raw values) so trees can learn to trust one model directly."""
    m = _model_matrix(df)
    if "bias_recent" in df.columns:
        bias = df["bias_recent"].to_numpy(dtype=float)
    else:
        bias = np.full(len(df), np.nan)
    return np.column_stack([m[:, 0], m[:, 1:] - m[:, :1], bias, seasonal_features(df["date"])])


def _fit_candidate(name: str, df: pd.DataFrame):
    """Returns predict(df) -> corrected forecast. Models learn the correction actual - forecast."""
    if name == "raw":
        return lambda d: d["forecast_c"].to_numpy(dtype=float)
    if name == "drift":
        return lambda d: (d["forecast_c"] - d["bias_recent"].fillna(0.0)).to_numpy(dtype=float)
    if name == "ens_mean":
        return lambda d: np.nanmean(_model_matrix(d), axis=1)
    feats = _blend_features if name == "blend" else _features
    if name == "linear":
        est = LinearRegression()
    else:
        est = HistGradientBoostingRegressor(
            max_iter=200, learning_rate=0.05, max_leaf_nodes=15, random_state=0
        )
    x = feats(df)
    keep = ~np.isnan(x).all(axis=0)  # a model with no history yet (all NaN) cannot be binned
    est.fit(x[:, keep], df["actual_c"] - df["forecast_c"])
    return lambda d: d["forecast_c"].to_numpy(dtype=float) + est.predict(feats(d)[:, keep])


class LeadCorrector:
    """Per-lead bias correction of a published forecast, with an empirical p10-p90 band.

    Selection and band use rolling-origin CV over the last n_folds * fold_days of training:
    each fold is predicted by models fit only on earlier days. With 4 x 91 days the
    out-of-fold residuals cover the most recent year, every season, in the current error regime.
    """

    def __init__(
        self,
        n_folds: int = 4,
        fold_days: int = 91,
        quantiles: tuple[float, float] = (0.1, 0.9),
        min_gain: float = 0.02,
    ):
        self.n_folds = n_folds
        self.fold_days = fold_days
        self.quantiles = quantiles
        self.min_gain = min_gain  # a correction must beat raw by this share of raw MAE

    def _oof(self, g: pd.DataFrame) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        """Out-of-fold (actual, prediction) per candidate."""
        end = g["date"].max() + pd.Timedelta(days=1)
        names = candidates(g)
        acts, dates, preds = [], [], {n: [] for n in names}
        for k in range(self.n_folds, 0, -1):
            start = end - pd.Timedelta(days=k * self.fold_days)
            val = g[(g["date"] >= start) & (g["date"] < start + pd.Timedelta(days=self.fold_days))]
            past = g[g["date"] < start]
            if val.empty or len(past) < 30:
                continue
            acts.append(val["actual_c"].to_numpy())
            dates.append(val["date"].to_numpy())
            for name in names:
                preds[name].append(_fit_candidate(name, past)(val))
        if not acts:
            raise ValueError("not enough history for cross-validation")
        actual = np.concatenate(acts)
        self._oof_dates = pd.DatetimeIndex(np.concatenate(dates))
        return {n: (actual, np.concatenate(p)) for n, p in preds.items()}

    def fit(self, df: pd.DataFrame) -> "LeadCorrector":
        self.method: dict[int, str] = {}
        self.val_mae: dict[int, dict[str, float]] = {}
        self.band: dict[int, tuple[float, float]] = {}
        self.models: dict[int, object] = {}
        self.oof_resid: dict[int, pd.Series] = {}  # chosen method, for adaptive_band
        self.all_models: dict[int, dict[str, object]] = {}  # every candidate, for the leaderboard
        for lead, g in df.groupby("lead_days"):
            g = g.sort_values("date")
            oof = self._oof(g)
            maes = {n: float(np.mean(np.abs(a - p))) for n, (a, p) in oof.items()}
            best = min(maes, key=maes.get)
            if maes[best] > maes["raw"] * (1 - self.min_gain):
                best = "raw"
            actual, pred = oof[best]
            lo, hi = np.quantile(actual - pred, self.quantiles)
            lead = int(lead)
            self.oof_resid[lead] = pd.Series(actual - pred, index=self._oof_dates)
            self.method[lead], self.val_mae[lead] = best, maes
            self.band[lead] = (min(float(lo), 0.0), max(float(hi), 0.0))
            self.all_models[lead] = {n: _fit_candidate(n, g) for n in oof}  # all training rows
            self.models[lead] = self.all_models[lead][best]
        return self

    def predict_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """Every candidate's prediction, one column per method (leaderboard only)."""
        names = list(next(iter(self.all_models.values())))
        out = pd.DataFrame(index=df.index, columns=names, dtype=float)
        for lead, g in df.groupby("lead_days"):
            for name, model in self.all_models[int(lead)].items():
                out.loc[g.index, name] = model(g)
        return out

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index, columns=["pred_c", "lo_c", "hi_c"], dtype=float)
        for lead, g in df.groupby("lead_days"):
            lead = int(lead)
            if lead not in self.models:
                raise ValueError(f"no model for lead {lead}; trained leads {sorted(self.models)}")
            pred = self.models[lead](g)
            lo, hi = self.band[lead]
            out.loc[g.index, "pred_c"] = pred
            out.loc[g.index, "lo_c"] = pred + lo
            out.loc[g.index, "hi_c"] = pred + hi
        return out


def adaptive_band(
    frame: pd.DataFrame,
    resid_hist: dict[int, pd.Series],
    window: int = 120,
    quantiles: tuple[float, float] = (0.1, 0.9),
    min_n: int = 30,
) -> pd.DataFrame:
    """p10-p90 range from the last `window` misses known when each forecast was issued.

    `resid_hist[lead]` is a date-indexed series of actual - forecast from before the frame
    (out-of-fold or validation residuals). Rows of `frame` with an `actual_c` add their own miss
    for later rows. A lead-L forecast for day D can use misses for days up to D-L-1. Where
    fewer than `min_n` misses are known, the whole history's quantiles are used.
    """
    out = pd.DataFrame(index=frame.index, columns=["lo_c", "hi_c"], dtype=float)
    for lead, g in frame.groupby("lead_days"):
        lead = int(lead)
        hist = resid_hist[lead].dropna()
        resid = hist
        if "actual_c" in g.columns:
            new = (g["actual_c"] - g["pred_c"]).set_axis(pd.DatetimeIndex(g["date"])).dropna()
            resid = pd.concat([hist[~hist.index.isin(new.index)], new]).sort_index()
        days = pd.date_range(resid.index.min(), max(resid.index.max(), g["date"].max()), freq="D")
        known = resid.reindex(days)
        # rolling over known misses only (a missing day is skipped, not counted)
        roll = known.dropna().rolling(window, min_periods=min_n)
        edges = {}
        fallbacks = np.quantile(hist, quantiles)
        for name, qv, fallback in zip(("lo_c", "hi_c"), quantiles, fallbacks, strict=True):
            s = roll.quantile(qv).reindex(days).ffill().shift(lead + 1)
            edges[name] = s.reindex(pd.DatetimeIndex(g["date"])).fillna(float(fallback)).to_numpy()
        pred = g["pred_c"].to_numpy(dtype=float)
        out.loc[g.index, "lo_c"] = pred + np.minimum(edges["lo_c"], 0.0)
        out.loc[g.index, "hi_c"] = pred + np.maximum(edges["hi_c"], 0.0)
    return out


def long_range_backtest(
    actual: pd.Series, clim, coef: np.ndarray, origins: Sequence, window: int = 3
) -> pd.DataFrame:
    """Forecast from each origin for leads 1..len(coef) and pair with what happened.

    `actual` is a contiguous daily series indexed by date. Rows past the data end are dropped.
    """
    base = pd.Series(clim.predict(actual.index), index=actual.index)
    recent = _recent_mean(actual - base, window)
    rows = []
    for origin in origins:
        x = recent.get(origin, np.nan)
        if np.isnan(x):
            continue
        for lead in range(1, len(coef) + 1):
            day = origin + pd.Timedelta(days=lead)
            if day not in actual.index or np.isnan(actual[day]):
                continue
            c = float(base[day])
            rows.append(
                (
                    origin,
                    lead,
                    day,
                    float(actual[day]),
                    c + coef[lead - 1] * x,
                    c,
                    float(actual[origin]),
                )
            )
    return pd.DataFrame(
        rows, columns=["origin", "lead_days", "date", "actual_c", "pred_c", "clim_c", "persist_c"]
    )


def residual_quantiles(
    bt: pd.DataFrame, quantiles: tuple[float, float] = (0.1, 0.9)
) -> dict[int, tuple[float, float]]:
    resid = bt["actual_c"] - bt["pred_c"]
    out = {}
    for lead, r in resid.groupby(bt["lead_days"]):
        lo, hi = np.quantile(r, quantiles)
        out[int(lead)] = (float(lo), float(hi))
    return out


def recent_anomaly(
    anom: pd.Series, today: pd.Timestamp, window: int = 3, max_age_days: int = 2
) -> float:
    """Mean anomaly over the last `window` observed days, which must be contiguous and recent.

    The long-range bands assume the anomaly is from yesterday; an older one would be decayed
    too little and carry a band that is too tight.
    """
    last = anom.last_valid_index()
    age = (today - last).days
    if age > max_age_days:
        raise ValueError(f"latest observation is {age} days old (max {max_age_days})")
    tail = anom.loc[:last].iloc[-window:]
    if len(tail) < window or tail.isna().any():
        raise ValueError(f"gap in the last {window} observed days before {last.date()}")
    return float(tail.mean())


def assemble_outlook(
    today: pd.Timestamp,
    live: pd.DataFrame,
    corrector,
    clim,
    coef: np.ndarray,
    recent_anomaly: float,
    long_quantiles: dict[int, tuple[float, float]],
    short_leads: int = 7,
    horizon: int = 30,
    long_pred: np.ndarray | None = None,
    long_source: str = "climatology + anomaly",
) -> pd.DataFrame:
    """Next `horizon` days: corrected forecast up to short_leads, then climatology + anomaly
    (or `long_pred`, e.g. from the LSTM, when given). Extra columns of `live` (other weather
    models, recent bias) are handed to the corrector.

    shortcut: leads count from `today`, while the anomaly is from the last observed day (usually
    yesterday), so the decay is applied one day early; fine at a 30-day horizon.
    """
    dates = pd.date_range(today + pd.Timedelta(days=1), periods=horizon, freq="D")
    raw = live.set_index("date")["forecast_c"].reindex(dates).to_numpy(dtype=float)
    out = pd.DataFrame(
        {"date": dates, "lead_days": np.arange(1, horizon + 1), "raw_forecast_c": raw}
    )
    base = clim.predict(dates)
    out["pred_c"] = base + coef[:horizon] * recent_anomaly if long_pred is None else long_pred
    out["lo_c"] = out["pred_c"] + [long_quantiles[n][0] for n in out["lead_days"]]
    out["hi_c"] = out["pred_c"] + [long_quantiles[n][1] for n in out["lead_days"]]
    out["source"] = long_source
    short = out["lead_days"] <= short_leads
    missing = out.loc[short & out["raw_forecast_c"].isna(), "lead_days"].tolist()
    if missing:
        raise ValueError(f"published forecast missing for leads {missing}; refetch it")
    if short.any():
        rows = out.loc[short, ["date", "lead_days"]].assign(
            forecast_c=out.loc[short, "raw_forecast_c"]
        )
        extra = live.set_index("date").drop(columns="forecast_c").reindex(rows["date"])
        for col in extra.columns:
            rows[col] = extra[col].to_numpy()
        pred = corrector.predict(rows)
        out.loc[short, ["pred_c", "lo_c", "hi_c"]] = pred[["pred_c", "lo_c", "hi_c"]].to_numpy()
        out.loc[short, "source"] = "corrected forecast"
    return out[["date", "lead_days", "pred_c", "lo_c", "hi_c", "raw_forecast_c", "source"]]
