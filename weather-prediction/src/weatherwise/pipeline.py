"""End-to-end sprint run: fetch real data, build SQL models, evaluate, forecast, capture results.

Everything the results page shows is written here to results/<sprint>/ from measured values.
"""

import argparse
import json
import platform
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
import numpy as np
import pandas as pd
import psycopg
import requests
import sklearn

from weatherwise import ingest, models, warehouse
from weatherwise.config import CITIES, database_url

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SHORT_LEADS = 7
HORIZON = 30
WINDOW = 3
# Published-forecast bias drifts as Open-Meteo upgrades models (tmin lead-1 bias +1.8 C in
# 2022, about -0.2 C in 2026). Ablation: a corrector trained on only the last TRAIN_DAYS.
TRAIN_DAYS = 365
VARIABLES = ("tmax", "tmin")
MIN_GAIN = 0.02  # the LSTM must beat the simple long-range model by this share on validation
TABLES = [
    "raw_actual_daily",
    "raw_published_hourly",
    "raw_live_forecast",
    "raw_user_observation",
    "stg_actual_daily",
    "stg_published_daily",
    "stg_quality_issues",
    "mart_forecast_error",
    "mart_error_by_lead",
    "mart_model_pairs",
    "mart_data_quality",
    "log_forecast",
    "app_model_eval",
    "mart_verification",
    "mart_scoreboard",
]


def city_today(city, now: datetime | None = None) -> date:
    """Today on the city's own clock. A forecast 'for tomorrow' means tomorrow there."""
    now = now or datetime.now(UTC)
    return now.astimezone(ZoneInfo(city.timezone)).date()


def choose_long(val_mae: dict[str, float], min_gain: float = MIN_GAIN) -> str:
    """Long-range method from validation MAE: the LSTM only on a clear win, else the simple
    damped-anomaly model."""
    best = min(val_mae, key=val_mae.get)
    return best if val_mae[best] <= val_mae["decay"] * (1 - min_gain) else "decay"


def log_rows(city: str, kind: str, var: str, frame: pd.DataFrame, logged_at) -> pd.DataFrame:
    """Forecast-log rows from a frame with date, lead_days, pred_c, lo_c, hi_c, published_c,
    method. The issue day is the target day minus the lead."""
    out = frame[["date", "lead_days", "pred_c", "lo_c", "hi_c", "published_c", "method"]].copy()
    out["issued_on"] = out["date"] - pd.to_timedelta(out["lead_days"], unit="D")
    return out.assign(city=city, kind=kind, variable=var, logged_at=logged_at)


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch_all(
    con, city, actuals_start: str, published_start: str, today: date, session=None
) -> None:
    session = session or requests.Session()
    end = (today - timedelta(days=1)).isoformat()
    log(f"[fetch] actuals (ERA5 archive) {actuals_start}..{end}")
    n = warehouse.load(con, "actual_daily", ingest.fetch_actuals(session, city, actuals_start, end))
    log(f"[load] raw_actual_daily rows={n}")
    year = int(published_start[:4])
    while year <= today.year:  # one request per year keeps payloads small
        start = max(published_start, f"{year}-01-01")
        stop = min(end, f"{year}-12-31")
        year += 1
        if start > stop:  # 1 January: the new year has no finished day yet
            continue
        df = ingest.fetch_published(session, city, start, stop)
        n = warehouse.load(con, "published_hourly", df)
        log(f"[fetch] published forecasts {start}..{stop} hourly values={len(df)} table rows={n}")
    live = ingest.fetch_live_forecast(session, city).assign(issued_on=pd.Timestamp(today))
    n = warehouse.load(con, "live_forecast", live)
    log(f"[load] raw_live_forecast rows={n} (issued_on={today})")
    for table, (rows, digest) in warehouse.checksum(con).items():
        log(f"[checksum] {table} rows={rows} digest={digest}")


def q(con, sql: str, params: list | None = None) -> pd.DataFrame:
    return warehouse.frame(con, sql, params)


def model_pairs(con, city: str) -> pd.DataFrame:
    """Every archived forecast next to what happened, all weather models side by side."""
    pairs = q(
        con,
        "select date, lead_days, variable, forecast_c, fc_gfs, fc_ecmwf, fc_gem, actual_c "
        "from mart_model_pairs where city = %s",
        [city],
    )
    pairs["date"] = pd.to_datetime(pairs["date"])
    return pairs


def daily_series(con, city: str, var: str) -> pd.Series:
    if var not in VARIABLES:  # formatted into SQL below
        raise ValueError(f"unknown variable {var!r}")
    df = q(
        con,
        f"select date, {var}_c as v from stg_actual_daily where city = %s order by date",
        [city],
    )
    s = df.set_index(pd.to_datetime(df["date"]))["v"].astype(float)
    return s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D"))


def last_days(pairs: pd.DataFrame, end: pd.Timestamp, days: int) -> pd.DataFrame:
    return pairs[(pairs["date"] >= end - pd.Timedelta(days=days)) & (pairs["date"] < end)]


def fit_short(pairs: pd.DataFrame, test_start) -> tuple:
    """Fit the per-lead corrector on rows before the test window; predict the test window."""
    train, test = models.split_by_date(pairs, test_start)
    corr = models.LeadCorrector().fit(train)
    test = test.assign(**corr.predict(test))
    # the range follows the misses known when each forecast was issued (see adaptive_band)
    return corr, train, test.assign(**models.adaptive_band(test, corr.oof_resid))


def short_leaderboard(corr, test: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    """Every candidate per lead: CV MAE (inside training) and test MAE. One row per method."""
    preds = corr.predict_all(test)
    cover = table.set_index("lead_days")["band_coverage_pct"]
    rows = []
    for lead, g in test.groupby("lead_days"):
        lead = int(lead)
        for name in preds.columns:
            chosen = corr.method[lead] == name
            rows.append(
                {
                    "lead_days": lead,
                    "method": name,
                    "cv_mae_c": round(corr.val_mae[lead][name], 3),
                    "test_mae_c": round((preds.loc[g.index, name] - g["actual_c"]).abs().mean(), 3),
                    "test_days": len(g),
                    "chosen": chosen,
                    "coverage_pct": float(cover[lead]) if chosen else np.nan,
                }
            )
    return pd.DataFrame(rows)


def evaluate_short(pairs: pd.DataFrame, actual: pd.Series, clim, test_start) -> tuple:
    corr, train, test = fit_short(pairs, test_start)
    return score_short(corr, train, test, actual, clim, test_start), test


def score_short(corr, train, test, actual: pd.Series, clim, test_start) -> pd.DataFrame:
    last_year = models.LeadCorrector().fit(last_days(train, test_start, TRAIN_DAYS))
    ablation = last_year.predict(test)["pred_c"]
    test = test.copy()
    test["clim_c"] = clim.predict(test["date"])
    test["persist_c"] = [
        actual.get(d - pd.Timedelta(days=int(n)), np.nan)
        for d, n in zip(test["date"], test["lead_days"], strict=True)
    ]
    rows = []
    for lead, g in test.groupby("lead_days"):
        g = g.dropna(subset=["persist_c"])
        err_raw = g["forecast_c"] - g["actual_c"]
        err_cor = g["pred_c"] - g["actual_c"]
        rows.append(
            {
                "lead_days": int(lead),
                "test_days": len(g),
                "published_mae_c": round(err_raw.abs().mean(), 2),
                "corrected_mae_c": round(err_cor.abs().mean(), 2),
                "last_365d_only_mae_c": round((ablation[g.index] - g["actual_c"]).abs().mean(), 2),
                "improvement_pct": round(
                    100 * (1 - err_cor.abs().mean() / err_raw.abs().mean()), 1
                ),
                "climatology_mae_c": round((g["clim_c"] - g["actual_c"]).abs().mean(), 2),
                "persistence_mae_c": round((g["persist_c"] - g["actual_c"]).abs().mean(), 2),
                "published_bias_c": round(err_raw.mean(), 2),
                "corrected_bias_c": round(err_cor.mean(), 2),
                "chosen_method": corr.method[int(lead)],
                "start_band_c": "{:+.1f} / {:+.1f}".format(*corr.band[int(lead)]),
                "band_coverage_pct": round(
                    100 * models.interval_coverage(g["actual_c"], g["lo_c"], g["hi_c"]), 1
                ),
            }
        )
    return pd.DataFrame(rows)


def calibrate_bands(actual: pd.Series) -> dict[int, tuple[float, float]]:
    """p10-p90 long-range residuals measured out of sample: fit on all but the final year of
    `actual`, then backtest origins inside that year."""
    fit_part = actual.iloc[:-365]
    obs = fit_part.dropna()
    clim = models.Climatology().fit(obs.index, obs.to_numpy())
    coef = models.fit_anomaly_decay(fit_part - clim.predict(fit_part.index), HORIZON, WINDOW)
    origins = actual.index[-365:-HORIZON]
    return models.residual_quantiles(
        models.long_range_backtest(actual, clim, coef, origins, WINDOW)
    )


def evaluate_long(actual: pd.Series, test_start) -> tuple:
    train = actual[actual.index < test_start]
    clim = models.Climatology().fit(train.dropna().index, train.dropna().to_numpy())
    anom = train - clim.predict(train.index)
    coef = models.fit_anomaly_decay(anom, HORIZON, WINDOW)
    bands = calibrate_bands(train)
    test_origins = actual.index[actual.index >= test_start - pd.Timedelta(days=1)]
    bt = models.long_range_backtest(actual, clim, coef, test_origins, WINDOW)
    bt["lo_c"] = bt["pred_c"] + bt["lead_days"].map(lambda n: bands[n][0])
    bt["hi_c"] = bt["pred_c"] + bt["lead_days"].map(lambda n: bands[n][1])
    rows = []
    for lead, g in bt.groupby("lead_days"):
        rows.append(
            {
                "lead_days": int(lead),
                "test_origins": len(g),
                "model_mae_c": round((g["pred_c"] - g["actual_c"]).abs().mean(), 2),
                "climatology_mae_c": round((g["clim_c"] - g["actual_c"]).abs().mean(), 2),
                "persistence_mae_c": round((g["persist_c"] - g["actual_c"]).abs().mean(), 2),
                "anomaly_kept": round(float(coef[lead - 1]), 3),
                "band_coverage_pct": round(
                    100 * models.interval_coverage(g["actual_c"], g["lo_c"], g["hi_c"]), 1
                ),
            }
        )
    return pd.DataFrame(rows), clim, coef, bands


def long_backtests(history: pd.Series, full: pd.Series, origins, use_lstm: bool) -> tuple:
    """Fit the long-range models on `history` only, then forecast from each origin in `full`.

    Returns ({method: backtest frame}, fitted parts). Both methods are scored on the same rows.
    """
    obs = history.dropna()
    clim = models.Climatology().fit(obs.index, obs.to_numpy())
    anom = history - clim.predict(history.index)
    coef = models.fit_anomaly_decay(anom, HORIZON, WINDOW)
    out = {"decay": models.long_range_backtest(full, clim, coef, origins, WINDOW)}
    fitted = {"clim": clim, "coef": coef}
    if use_lstm:
        from weatherwise import deep  # torch loads only when the LSTM is asked for

        net = deep.AnomalyLSTM(horizon=HORIZON).fit(anom)
        pred = net.predict(full - clim.predict(full.index), origins)
        both = out["decay"].merge(pred, on=["origin", "lead_days"])
        out["decay"] = both.drop(columns="anom_pred")
        out["lstm"] = both.assign(pred_c=both["clim_c"] + both["anom_pred"]).drop(
            columns="anom_pred"
        )
        # mix: the plain average of the two. Averaging two imperfect models is rarely the worst.
        out["mix"] = out["decay"].assign(
            pred_c=(out["decay"]["pred_c"] + out["lstm"]["pred_c"]) / 2
        )
        fitted["net"] = net
    return out, fitted


def mae_by_lead(bt: pd.DataFrame, col: str = "pred_c") -> pd.Series:
    return (bt[col] - bt["actual_c"]).abs().groupby(bt["lead_days"]).mean()


def select_long(series: pd.Series, use_lstm: bool, pin: str | None = None) -> tuple:
    """Choose the long-range method on the last year of `series`, with models fit only on the
    days before that year. Returns (chosen, that year's misses by lead, val_mae, by_lead).
    `pin` keeps a method chosen earlier, when it is one of the methods run here."""
    val, _ = long_backtests(series.iloc[:-365], series, series.index[-365:-HORIZON], use_lstm)
    by_lead = {m: mae_by_lead(bt) for m, bt in val.items()}
    val_mae = {m: float(s.loc[SHORT_LEADS + 1 :].mean()) for m, s in by_lead.items()}
    chosen = pin if pin in val else choose_long(val_mae)
    resid = {
        int(lead): (g["actual_c"] - g["pred_c"]).set_axis(pd.DatetimeIndex(g["date"]))
        for lead, g in val[chosen].groupby("lead_days")
    }
    return chosen, resid, val_mae, by_lead


def evaluate_long_methods(actual: pd.Series, test_start, use_lstm: bool = True) -> dict:
    """Long-range candidates on the test window. Selection and bands come from the last
    training year (select_long), never from the test window."""
    train = actual[actual.index < test_start]
    chosen, resid, val_mae, val_by_lead = select_long(train, use_lstm)
    origins = actual.index[actual.index >= test_start - pd.Timedelta(days=1)]
    test, fitted = long_backtests(train, actual, origins, use_lstm)
    bt = test[chosen].copy()
    bt = bt.assign(**models.adaptive_band(bt, resid))
    by_lead = {m: mae_by_lead(f) for m, f in test.items()}
    rows, board = [], []
    for lead, g in bt.groupby("lead_days"):
        lead = int(lead)
        row = {
            "lead_days": lead,
            "test_origins": len(g),
            "model_mae_c": round(by_lead[chosen][lead], 2),
        }
        row |= {f"{m}_mae_c": round(s[lead], 2) for m, s in by_lead.items()}
        cover = round(100 * models.interval_coverage(g["actual_c"], g["lo_c"], g["hi_c"]), 1)
        row |= {
            "climatology_mae_c": round(mae_by_lead(g, "clim_c")[lead], 2),
            "persistence_mae_c": round(mae_by_lead(g, "persist_c")[lead], 2),
            "anomaly_kept": round(float(fitted["coef"][lead - 1]), 3),
            "chosen_method": chosen,
            "band_coverage_pct": cover,
        }
        rows.append(row)
        if lead <= SHORT_LEADS:
            continue
        for name in by_lead:
            board.append(
                {
                    "lead_days": lead,
                    "method": name,
                    "cv_mae_c": round(float(val_by_lead[name][lead]), 3),
                    "test_mae_c": round(float(by_lead[name][lead]), 3),
                    "test_days": len(g),
                    "chosen": name == chosen,
                    "coverage_pct": cover if name == chosen else np.nan,
                }
            )
    return {
        "table": pd.DataFrame(rows),
        "bt": bt,
        "chosen": chosen,
        "val_mae": val_mae,
        "board": pd.DataFrame(board),
    }


def live_frame(con, city: str, var: str, today: pd.Timestamp, pairs: pd.DataFrame) -> pd.DataFrame:
    """Today's forecast from every weather model, one row per target day, with the recent bias
    of each lead as known today."""
    if var not in VARIABLES:  # formatted into SQL below
        raise ValueError(f"unknown variable {var!r}")
    live = q(
        con,
        f"""select date,
            max(case when model = 'best_match' then {var}_c end) as forecast_c,
            max(case when model = 'gfs_seamless' then {var}_c end) as fc_gfs,
            max(case when model = 'ecmwf_ifs025' then {var}_c end) as fc_ecmwf,
            max(case when model = 'gem_seamless' then {var}_c end) as fc_gem
        from raw_live_forecast where city = %s and issued_on = %s group by date order by date""",
        [city, today.date()],
    )
    live["date"] = pd.to_datetime(live["date"])
    live = live[live["date"] > today]
    future = live[["date", "forecast_c"]].assign(
        lead_days=(live["date"] - today).dt.days, actual_c=np.nan
    )
    future = future[future["lead_days"] <= SHORT_LEADS]
    history = pairs[["date", "lead_days", "forecast_c", "actual_c"]]
    both = models.add_recent_bias(pd.concat([history, future], ignore_index=True))
    bias = both.iloc[len(history) :].set_index("date")["bias_recent"]
    return live.assign(bias_recent=live["date"].map(bias))


def build_outlook(
    con,
    city: str,
    var: str,
    actual: pd.Series,
    pairs: pd.DataFrame,
    today: pd.Timestamp,
    use_lstm: bool = False,
    pin: dict | None = None,
) -> pd.DataFrame:
    """Production fit on all data (the evaluation above used the holdout). `pin` =
    {"short": {lead: method}, "long": method} keeps the methods of an earlier selection
    (the daily run); without it the methods are chosen again."""
    pin = pin or {}
    obs = actual.dropna()
    clim = models.Climatology().fit(obs.index, obs.to_numpy())
    anom = actual - clim.predict(actual.index)
    coef = models.fit_anomaly_decay(anom, HORIZON, WINDOW)
    corr = models.LeadCorrector().fit(pairs, pin=pin.get("short"))
    live = live_frame(con, city, var, today, pairs)
    recent = models.recent_anomaly(anom, today, WINDOW)
    chosen, resid, _, _ = select_long(actual, use_lstm, pin.get("long"))
    long_pred, source = None, "climatology + anomaly"
    if chosen != "decay":
        from weatherwise import deep

        last = anom.last_valid_index()
        net = deep.AnomalyLSTM(horizon=HORIZON).fit(anom)
        ahead = net.predict(anom, [last]).set_index("lead_days")["anom_pred"]
        dates = pd.date_range(today + pd.Timedelta(days=1), periods=HORIZON, freq="D")
        # the network counts leads from the last observed day, the outlook from today
        steps = [min((d - last).days, HORIZON) for d in dates]
        lstm_anom = ahead.loc[steps].to_numpy()
        decay_anom = coef[:HORIZON] * recent
        long_anom = lstm_anom if chosen == "lstm" else (lstm_anom + decay_anom) / 2
        long_pred = clim.predict(dates) + long_anom
        source = "climatology + LSTM anomaly" if chosen == "lstm" else "climatology + mixed anomaly"
    flat = {n: (0.0, 0.0) for n in range(1, HORIZON + 1)}  # ranges are set just below
    out = models.assemble_outlook(
        today, live, corr, clim, coef, recent, flat, SHORT_LEADS, HORIZON, long_pred, source
    )
    short = out["lead_days"] <= SHORT_LEADS
    band = pd.concat(
        [
            models.adaptive_band(out[short], corr.oof_resid),
            models.adaptive_band(out[~short], resid),
        ]
    )
    out[["lo_c", "hi_c"]] = band
    out["method"] = out["lead_days"].map(corr.method).fillna(chosen)
    kept = out["method"].eq("raw")
    out.loc[kept, "source"] = "published forecast (kept)"
    out.loc[~kept & (out["lead_days"] <= SHORT_LEADS), "source"] = "corrected: " + out["method"]
    return out


def charts(
    out: Path,
    con,
    city: str,
    outlook: dict,
    short_test: pd.DataFrame,
    short_eval: pd.DataFrame,
    long_eval: pd.DataFrame,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    err = q(
        con,
        "select lead_days, error_c from mart_forecast_error where city = %s and variable = 'tmax'",
        [city],
    )
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.boxplot(
        [err.loc[err.lead_days == n, "error_c"] for n in range(1, 8)],
        whis=(5, 95),
        showfliers=False,
    )
    ax.axhline(0, color="#888", lw=0.8)
    ax.set(
        xlabel="forecast issued N days ahead",
        ylabel="forecast - actual (C)",
        title="Published max-temp forecast error (box p25-p75, whiskers p5-p95)",
    )
    fig.tight_layout()
    fig.savefig(out / "01_published_error_by_lead.png", dpi=110)
    plt.close(fig)

    t = outlook["tmax"]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.fill_between(t["date"], t["lo_c"], t["hi_c"], alpha=0.25, label="p10-p90 range")
    ax.plot(t["date"], t["pred_c"], marker="o", ms=3, label="weatherwise")
    ax.plot(t["date"], t["raw_forecast_c"], ls="--", label="published forecast (raw)")
    ax.axvline(t["date"].iloc[SHORT_LEADS - 1], color="#888", lw=0.8)
    ax.set(ylabel="max temp (C)", title="Next 30 days: max temperature outlook")
    ax.legend(fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out / "02_outlook_tmax.png", dpi=110)
    plt.close(fig)

    s = short_test[(short_test.lead_days == 1)].sort_values("date").tail(90)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(s["date"], s["actual_c"], color="k", lw=1.4, label="actual")
    ax.plot(s["date"], s["forecast_c"], lw=1, label="published 1 day ahead")
    ax.plot(s["date"], s["pred_c"], lw=1, label="weatherwise corrected")
    ax.set(ylabel="max temp (C)", title="Last 90 test days: day-ahead forecast vs actual")
    ax.legend(fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out / "03_day_ahead_vs_actual.png", dpi=110)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(long_eval.lead_days, long_eval.model_mae_c, label="long-range model (chosen)")
    ax.plot(long_eval.lead_days, long_eval.climatology_mae_c, label="climatology only")
    ax.plot(long_eval.lead_days, long_eval.persistence_mae_c, label="persistence")
    ax.plot(short_eval.lead_days, short_eval.published_mae_c, marker="o", label="published")
    ax.plot(short_eval.lead_days, short_eval.corrected_mae_c, marker="o", label="corrected")
    ax.set(xlabel="lead (days)", ylabel="MAE (C)", title="Max-temp error by lead, test window")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "04_mae_by_lead.png", dpi=110)
    plt.close(fig)


def run_city(con, city, today: date, test_months: int = 12, use_lstm: bool = True) -> dict:
    """Evaluate on the held-out window, build today's outlook, and record both in the database
    (forecast log, leaderboard, run stamp). Needs build_models to have run on fresh data."""
    test_start = pd.Timestamp(today) - pd.DateOffset(months=test_months)
    log(f"[split] train < {test_start.date()} <= test")
    pairs_all = model_pairs(con, city.name)
    now = pd.Timestamp(datetime.now(UTC).replace(tzinfo=None, microsecond=0))
    summary, outlook, short_tests, boards, logs = {}, {}, {}, [], []
    for var in VARIABLES:
        actual = daily_series(con, city.name, var)
        pairs = models.add_recent_bias(
            pairs_all[pairs_all.variable == var].drop(columns="variable").reset_index(drop=True)
        )
        seen = actual[actual.index < test_start].dropna()
        clim = models.Climatology().fit(seen.index, seen.to_numpy())  # baseline column only
        long = evaluate_long_methods(actual, test_start, use_lstm)
        corr, train, short_test = fit_short(pairs, test_start)
        short_eval = score_short(corr, train, short_test, actual, clim, test_start)
        out = build_outlook(con, city.name, var, actual, pairs, pd.Timestamp(today), use_lstm)
        outlook[var], short_tests[var] = out, short_test
        summary[var] = {"short": short_eval, "long": long["table"], "long_val": long["val_mae"]}
        boards.append(
            pd.concat([short_leaderboard(corr, short_test, short_eval), long["board"]]).assign(
                city=city.name, variable=var
            )
        )
        hind_short = short_test.assign(
            published_c=short_test["forecast_c"], method=short_test["lead_days"].map(corr.method)
        )
        # The backtest forecasts from the last observed day (origin). A forecast is issued the
        # day after its newest observation, so it is logged one lead shorter: issued = origin + 1.
        replay = long["bt"].assign(lead_days=long["bt"]["lead_days"] - 1)
        hind_long = replay[replay["lead_days"] > SHORT_LEADS].assign(
            published_c=np.nan, method=long["chosen"]
        )
        live = out.rename(columns={"raw_forecast_c": "published_c"})
        logs += [
            log_rows(city.name, "hindcast", var, hind_short, now),
            log_rows(city.name, "hindcast", var, hind_long, now),
            log_rows(city.name, "live", var, live, now),
        ]
        log(
            f"[eval {var}] lead1 published MAE {short_eval.published_mae_c.iloc[0]} -> "
            f"{short_eval.corrected_mae_c.iloc[0]} ({short_eval.chosen_method.iloc[0]}); "
            f"lead30 {long['chosen']} {long['table'].model_mae_c.iloc[-1]} vs clim "
            f"{long['table'].climatology_mae_c.iloc[-1]}; long-range validation MAE "
            + ", ".join(f"{m} {v:.3f}" for m, v in long["val_mae"].items())
        )
    n = warehouse.load(con, "forecast_log", pd.concat(logs, ignore_index=True))
    log(f"[load] log_forecast rows={n}")
    board = pd.concat(boards, ignore_index=True)
    warehouse.load(con, "model_eval", board)
    stamp = {"city": city.name, "run_utc": now, "today": today, "test_start": test_start}
    warehouse.load(con, "run", pd.DataFrame([stamp]))
    return {
        "test_start": test_start,
        "summary": summary,
        "outlook": outlook,
        "short_tests": short_tests,
        "board": board,
    }


def refresh(con, city, today: date, *, use_lstm: bool = True, data_dir: Path | None = None) -> dict:
    """Fetch, rebuild the SQL models, evaluate and forecast for one city. Used by the pipeline
    and by the site's refresh button."""
    fetch_all(con, city, "1995-01-01", "2022-01-01", today)
    warehouse.build_models(con)
    result = run_city(con, city, today, use_lstm=use_lstm)
    if data_dir is not None:
        warehouse.backup(con, data_dir)
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--city", default="torrance", choices=sorted(CITIES))
    p.add_argument("--database-url", default=database_url())
    p.add_argument("--data-dir", default=str(ROOT / "data"), help="CSV backups live here")
    p.add_argument("--sprint", default="sprint-03")
    p.add_argument("--actuals-start", default="1995-01-01")
    p.add_argument("--published-start", default="2022-01-01")
    p.add_argument("--test-months", type=int, default=12)
    p.add_argument("--skip-fetch", action="store_true", help="reuse data already in the db")
    p.add_argument("--no-lstm", action="store_true", help="skip the LSTM long-range candidate")
    p.add_argument(
        "--fetch-only", action="store_true", help="fetch and load, print checksums, stop"
    )
    a = p.parse_args(argv)
    city = CITIES[a.city]
    today = city_today(city)
    out = ROOT / "results" / a.sprint
    for sub in ("metrics", "charts", "tables"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    con = warehouse.connect(a.database_url)
    warehouse.restore(con, a.data_dir)
    log(
        f"[start] city={city.name} today={today} (city clock) db={con.info.dbname} "
        f"utc={datetime.now(UTC):%FT%TZ}"
    )
    if not a.skip_fetch:
        fetch_all(con, city, a.actuals_start, a.published_start, today)
    if a.fetch_only:  # reload evidence: the checksums must equal the previous run's
        con.close()
        return 0
    warehouse.build_models(con)
    res = run_city(con, city, today, a.test_months, use_lstm=not a.no_lstm)
    warehouse.backup(con, a.data_dir)
    for t in TABLES:
        snap = warehouse.snapshot(con, t, n=6)
        (out / "tables" / f"{t}.json").write_text(json.dumps(snap, indent=1), encoding="utf-8")
        log(f"[table] {t}: {snap['row_count']} rows")

    metrics = out / "metrics"
    by_lead = q(
        con,
        "select * from mart_error_by_lead where city = %s order by variable, lead_days",
        [city.name],
    ).drop(columns="city")
    by_lead.to_csv(metrics / "02_published_error_by_lead.csv", index=False)
    worst = q(
        con,
        "select date, lead_days, variable, forecast_c, actual_c, "
        "cast(round(cast(error_c as numeric), 1) as double precision) "
        "as error_c from mart_forecast_error where city = %s and lead_days = 1 "
        "order by abs(error_c) desc, date desc limit 12",
        [city.name],
    )
    worst.to_csv(metrics / "03_worst_day_ahead_misses.csv", index=False)
    summary, outlook = res["summary"], res["outlook"]
    for var in VARIABLES:
        summary[var]["short"].to_csv(metrics / f"04_short_range_eval_{var}.csv", index=False)
        summary[var]["long"].to_csv(metrics / f"05_long_range_eval_{var}.csv", index=False)
        board = res["board"][res["board"].variable == var]
        wide = board.pivot(index="lead_days", columns="method", values="test_mae_c").round(2)
        wide["chosen"] = board[board.chosen].set_index("lead_days")["method"]
        wide.reset_index().to_csv(metrics / f"06_leaderboard_test_mae_{var}.csv", index=False)
    q(con, "select * from mart_data_quality where city = %s order by source", [city.name]).drop(
        columns="city"
    ).to_csv(metrics / "07_data_quality.csv", index=False)
    q(
        con,
        "select source, reason, count(*) as rejected_rows, min(seen_at) as first_seen, "
        "max(seen_at) as last_seen from stg_quality_issues where city = %s "
        "group by source, reason order by source, reason",
        [city.name],
    ).to_csv(metrics / "08_cleaning_rejections.csv", index=False)

    t, n = outlook["tmax"], outlook["tmin"]
    table = pd.DataFrame(
        {
            "date": t["date"].dt.strftime("%a %d %b"),
            "lead_days": t["lead_days"],
            "max_c": t["pred_c"].round(1),
            "max_range_c": [f"{lo:.1f} - {hi:.1f}" for lo, hi in zip(t.lo_c, t.hi_c, strict=True)],
            "published_max_c": t["raw_forecast_c"].round(1),
            "min_c": n["pred_c"].round(1),
            "min_range_c": [f"{lo:.1f} - {hi:.1f}" for lo, hi in zip(n.lo_c, n.hi_c, strict=True)],
            "published_min_c": n["raw_forecast_c"].round(1),
            "max_method": t["source"],
            "min_method": n["source"],
        }
    )
    table.to_csv(metrics / "01_outlook_next_30_days.csv", index=False)
    charts(
        out / "charts",
        con,
        city.name,
        outlook,
        res["short_tests"]["tmax"],
        summary["tmax"]["short"],
        summary["tmax"]["long"],
    )
    write_meta(out, con, city, today, res["test_start"], by_lead, summary, a)
    log(f"[done] wrote {out.relative_to(ROOT)}")
    con.close()
    return 0


def _leads(leads: list[int]) -> str:
    return ", ".join(str(n) for n in leads) if leads else "none"


def short_range_finding(label: str, ev: pd.DataFrame) -> str:
    """One finding from a short-range eval table: where raw was kept, where correction helped,
    the worst lead, and the measured range coverage. Built only from the table."""
    raw = ev.loc[ev.chosen_method == "raw", "lead_days"].tolist()
    helped = ev.loc[ev.improvement_pct > 0, "lead_days"].tolist()
    worst = ev.loc[ev.improvement_pct.idxmin()]
    cov = ev.band_coverage_pct
    if worst.improvement_pct < 0:
        worst_txt = (
            f"lead {int(worst.lead_days)} got worse: {worst.published_mae_c} -> "
            f"{worst.corrected_mae_c} C ({worst.improvement_pct:+.1f}%)"
        )
    else:
        worst_txt = "no lead got worse"
    helped_txt = f"lead {_leads(helped)}" if helped else "no lead"
    kept_txt = (
        f"kept the published forecast at lead {_leads(raw)} (no correction beat it in CV)"
        if raw
        else "a correction was chosen in CV at every lead"
    )
    return (
        f"{label}: {kept_txt}; correction lowered error at {helped_txt}; {worst_txt}. "
        f"The p10-p90 range held the "
        f"actual value on {cov.min():.1f}% to {cov.max():.1f}% of days (target 80%)."
    )


def write_meta(out: Path, con, city, today, test_start, by_lead, summary, a) -> None:
    """meta.json for the results page. Findings are built from measured numbers only."""
    tmax = by_lead[by_lead.variable == "tmax"].set_index("lead_days")
    rng = q(
        con,
        "select min(date), max(date), count(*) from mart_forecast_error "
        "where city = %s and variable = 'tmax' and lead_days = 1",
        [city.name],
    ).iloc[0]
    first, last = (pd.Timestamp(v).date() for v in rng.iloc[:2])
    cov = {(v, k): summary[v][k].band_coverage_pct for v in VARIABLES for k in ("short", "long")}
    cov_txt = "; ".join(f"{v} {k} {c.min():.0f}-{c.max():.0f}%" for (v, k), c in cov.items())
    long_lines = []
    for v, label in (("tmax", "max"), ("tmin", "min")):
        lg = summary[v]["long"].iloc[-1]
        long_lines.append(
            f"{label} temp lead 30: model {lg.model_mae_c} C vs climatology "
            f"{lg.climatology_mae_c} C vs persistence {lg.persistence_mae_c} C"
        )
    corr = models.LeadCorrector()
    same = q(
        con,
        "select cast(round(100 * avg(case when forecast_c = fc_gfs then 1.0 else 0.0 end), 1) "
        "as double precision) as pct "
        "from mart_model_pairs where city = %s and fc_gfs is not null",
        [city.name],
    ).iloc[0, 0]
    week, month = [], []
    for v, label in (("tmax", "Daily high"), ("tmin", "Daily low")):
        sh = summary[v]["short"]
        pub, cor = sh.published_mae_c.mean(), sh.corrected_mae_c.mean()
        picks = ", ".join(f"{m} x{n}" for m, n in sh.chosen_method.value_counts().items())
        week.append(
            f"{label}, 1-7 days ahead on the test window: the published forecast missed by "
            f"{pub:.2f} C on average, weatherwise by {cor:.2f} C ({100 * (cor / pub - 1):+.0f}%). "
            f"Methods picked in CV, before the test window was used: {picks}."
        )
        lg = summary[v]["long"]
        far = lg[lg.lead_days > SHORT_LEADS]
        names = [c[: -len("_mae_c")] for c in far.columns if c.endswith("_mae_c")]
        names = [n for n in names if n not in ("model", "persistence")]
        scores = ", ".join(f"{n} {far[f'{n}_mae_c'].mean():.2f}" for n in names)
        val = ", ".join(f"{m} {x:.2f}" for m, x in summary[v]["long_val"].items())
        month.append(
            f"{label}, 8-30 days ahead: validation picked {far.chosen_method.iloc[0]} "
            f"(validation MAE: {val}). Test-window MAE in C: {scores}."
        )
    findings = [
        *week,
        *month,
        f"For {city.name}, Open-Meteo's best_match forecast equals gfs_seamless on {same}% of "
        "rows, so the blend really has three independent weather models, not four.",
        f"Published day-ahead max-temp forecasts for {city.name} ({first} to {last}, "
        f"{rng.iloc[2]} days) missed by {tmax.loc[1, 'mae_c']} C on average; "
        f"{tmax.loc[1, 'share_off_2c'] * 100:.0f}% of days were off by 2 C or more and "
        f"{tmax.loc[1, 'share_off_3c'] * 100:.0f}% by 3 C or more "
        f"(worst {tmax.loc[1, 'max_abs_error_c']} C).",
        f"Forecasts issued 7 days ahead missed by {tmax.loc[7, 'mae_c']} C on average; "
        f"{tmax.loc[7, 'share_off_3c'] * 100:.0f}% of days were off by 3 C or more.",
        f"Bias: published max temps run {tmax.loc[1, 'bias_c']:+.2f} C at lead 1 over the whole "
        "period (positive = forecast too warm); it drifts by year as the upstream model changes.",
        f"Test window ({test_start.date()} onward), "
        + short_range_finding("max temp", summary["tmax"]["short"]),
        short_range_finding("min temp", summary["tmin"]["short"]),
        "Beyond a week: " + "; ".join(long_lines) + ".",
    ]
    meta = {
        "title": f"{a.sprint}: Postgres port of the multi-model forecast, forecast log and "
        f"verification site ({city.name})",
        "goal": "Run everything built in sprint 02 on Postgres in Docker (migrations, repeatable "
        "loads, same numbers). "
        "Beat the published forecast where the data allows it (blend of weather models, "
        "recent-bias tracking, an LSTM for days 8-30), keep every forecast in a log, and let the "
        "user check any day they observed against what was forecast, on a local site.",
        "pattern": "batch ELT: raw -> staging -> marts (Postgres) + per-lead MOS + forecast log "
        "+ FastAPI site",
        "findings": findings,
        "commands": ["make test", "make check", "make mutate", "make run", "make site"],
        "scripts": sorted(
            str(p.relative_to(ROOT)).replace("\\", "/")
            for p in [
                *(ROOT / "sql").rglob("*.sql"),
                *(ROOT / "src").rglob("*.py"),
                *(ROOT / "scripts").glob("*.py"),
                *(ROOT / "web").glob("*.*"),
            ]
        ),
        "table_order": TABLES,
        "captions": {
            "01_outlook_next_30_days.csv": {
                "title": f"Outlook from {today}: next 30 days",
                "note": "Range = p10-p90 of the last 120 misses known on the issue day, "
                f"aiming for 8 in 10 days inside. Measured on the test window it held: {cov_txt}. "
                "Days 1-7 use the published forecast, corrected by the method CV picked. Days "
                "8-30 are climatology plus an anomaly forecast, because no archived forecasts "
                "past 7 days exist to check the published 8-16 day values (shown as "
                "published_* for reference).",
            },
            "02_published_error_by_lead.csv": {
                "title": "How wrong published forecasts were, by lead",
                "note": "error = forecast - actual. share_off_2c = fraction of days off by 2 C "
                "or more.",
            },
            "03_worst_day_ahead_misses.csv": {
                "title": "Worst day-ahead misses",
                "note": "Lead 1, largest absolute errors.",
            },
            "04_short_range_eval_tmax.csv": {
                "title": "Next-week model vs baselines on the test window: max temp",
                "note": f"Same days for every method. chosen_method is picked by "
                f"{corr.n_folds}-fold rolling-origin CV over the last training year and must "
                f"beat raw by {corr.min_gain:.0%}, else the published forecast is kept. "
                "last_365d_only_mae_c = ablation trained on the final year only. "
                "start_band_c = the range the model starts the test window with; "
                "band_coverage_pct = how often the adaptive range held the actual value.",
            },
            "04_short_range_eval_tmin.csv": {
                "title": "Next-week model vs baselines: min temp",
                "note": "",
            },
            "05_long_range_eval_tmax.csv": {
                "title": "Next-month model vs baselines on the test window: max temp",
                "note": "lead_days here counts from the last observed day, one more than the "
                "lead the same forecast has in the forecast log. "
                "model_mae_c = the method validation picked (chosen_method). "
                "decay = climatology + fading anomaly, lstm = climatology + LSTM anomaly, "
                "mix = their average. anomaly_kept = share of today's anomaly the decay model "
                "carries to that lead.",
            },
            "06_leaderboard_test_mae_tmax.csv": {
                "title": "Every method on the test window: daily high (MAE, C)",
                "note": "raw = published forecast; linear, gbm = fixed corrections; drift = "
                "recent-bias correction; ens_mean = average of the weather models; blend = "
                "boosting on all models; decay, lstm, mix = long-range methods. chosen was "
                "picked on training data only, so it is not always the row minimum.",
            },
            "06_leaderboard_test_mae_tmin.csv": {
                "title": "Every method on the test window: daily low (MAE, C)",
                "note": "",
            },
            "07_data_quality.csv": {
                "title": "Data health after cleaning",
                "note": "rejected_days = days dropped by the cleaning rules (impossible value, "
                "max below min, or a forecast day without all 24 hours); missing_days = "
                "calendar days inside the range with no usable row.",
            },
            "08_cleaning_rejections.csv": {
                "title": "Rows rejected by value checks",
                "note": "Empty means every value was inside -60..60 C and max >= min.",
            },
            "05_long_range_eval_tmin.csv": {
                "title": "Next-month model vs baselines: min temp",
                "note": "",
            },
        },
        "limits": [
            "Actuals are ERA5 reanalysis for the grid cell, not a weather station; the last few "
            "days of the archive are preliminary.",
            "Published forecasts are Open-Meteo's best-match model (previous_dayN hourly values "
            "aggregated to daily max/min), not a specific app's forecast.",
            "Leads 8-30 have no day-level skill in any public model; the 30-day line is a "
            "seasonal expectation with a measured range, not a weather forecast.",
            f"One test window of {a.test_months} months; MAE differences under about 0.1 C "
            "are within noise.",
            "Training rows are cut on target date, not issue date: up to 6 days of actuals just "
            "before the test window were not yet known when a lead-7 forecast was issued "
            "(about 0.1% of rows).",
            "Temperature only. Rain is fetched but not modelled this sprint.",
            "The site compares your reading with a forecast of the grid-cell value. A yard "
            "thermometer or a nearby airport can sit a steady 1-3 C away from the grid data; "
            "the scoreboard reports that gap separately.",
            "Method list revised once after seeing sprint-02 test numbers (adaptive range and "
            "the mix candidate were added then). The clean check from here on is the live "
            "forecast log against entries on the site.",
            "Recent-bias and adaptive-range inputs assume yesterday's actual is in the archive "
            "when today's forecast is made; the newest archive days are preliminary.",
            "A forecast issued during the day is up to a day fresher than the lead it is scored "
            "as (previous_dayN means at least N x 24 hours old).",
        ],
        "provenance": {
            "run_utc": f"{datetime.now(UTC):%FT%TZ}",
            "city": city.__dict__,
            "test_start": str(test_start.date()),
            "args": {k: v for k, v in vars(a).items() if k != "database_url"},
            "python": platform.python_version(),
            "psycopg": psycopg.__version__,
            "postgres": con.info.parameter_status("server_version"),
            "pandas": pd.__version__,
            "sklearn": sklearn.__version__,
            "torch": __import__("torch").__version__,
        },
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
