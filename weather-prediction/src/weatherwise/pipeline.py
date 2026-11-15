"""End-to-end sprint run: fetch real data, build SQL models, evaluate, forecast, capture results.

Everything the results page shows is written here to results/<sprint>/ from measured values.
"""

import argparse
import json
import platform
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import matplotlib
import numpy as np
import pandas as pd
import requests
import sklearn

from weatherwise import ingest, models, warehouse
from weatherwise.config import CITIES

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
TABLES = [
    "raw_actual_daily",
    "raw_published_hourly",
    "raw_live_forecast",
    "stg_actual_daily",
    "stg_published_daily",
    "mart_forecast_error",
    "mart_error_by_lead",
]


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


def q(con, sql: str, params: list | None = None) -> pd.DataFrame:
    return con.execute(sql, params or []).df()


def daily_series(con, city: str, var: str) -> pd.Series:
    assert var in VARIABLES, var  # formatted into SQL below
    df = q(
        con, f"select date, {var}_c as v from stg_actual_daily where city = ? order by date", [city]
    )
    s = df.set_index(pd.to_datetime(df["date"]))["v"].astype(float)
    return s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D"))


def last_days(pairs: pd.DataFrame, end: pd.Timestamp, days: int) -> pd.DataFrame:
    return pairs[(pairs["date"] >= end - pd.Timedelta(days=days)) & (pairs["date"] < end)]


def evaluate_short(pairs: pd.DataFrame, actual: pd.Series, clim, test_start) -> tuple:
    train, test = models.split_by_date(pairs, test_start)
    corr = models.LeadCorrector().fit(train)
    last_year = models.LeadCorrector().fit(last_days(train, test_start, TRAIN_DAYS))
    ablation = last_year.predict(test)["pred_c"]
    pred = corr.predict(test)
    test = test.assign(**pred)
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
                "band_p10_p90_c": "{:+.1f} / {:+.1f}".format(*corr.band[int(lead)]),
                "band_coverage_pct": round(
                    100 * models.interval_coverage(g["actual_c"], g["lo_c"], g["hi_c"]), 1
                ),
            }
        )
    return pd.DataFrame(rows), test


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


def build_outlook(
    con, city: str, var: str, actual: pd.Series, pairs: pd.DataFrame, today: pd.Timestamp
) -> pd.DataFrame:
    """Production fit on all data (the evaluation above used the holdout)."""
    assert var in VARIABLES, var  # formatted into SQL below
    obs = actual.dropna()
    clim = models.Climatology().fit(obs.index, obs.to_numpy())
    anom = actual - clim.predict(actual.index)
    coef = models.fit_anomaly_decay(anom, HORIZON, WINDOW)
    bands = calibrate_bands(actual)
    corr = models.LeadCorrector().fit(pairs)
    live = q(
        con,
        f"select date, {var}_c as forecast_c from raw_live_forecast "
        "where city = ? and issued_on = ? order by date",
        [city, today.date()],
    )
    live["date"] = pd.to_datetime(live["date"])
    recent = models.recent_anomaly(anom, today, WINDOW)
    out = models.assemble_outlook(
        today, live, corr, clim, coef, recent, bands, SHORT_LEADS, HORIZON
    )
    kept = out["lead_days"].map(corr.method).eq("raw")
    out.loc[kept, "source"] = "published forecast (kept)"
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
        "select lead_days, error_c from mart_forecast_error where city = ? and variable = 'tmax'",
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
    ax.plot(long_eval.lead_days, long_eval.model_mae_c, label="climatology + anomaly (model)")
    ax.plot(long_eval.lead_days, long_eval.climatology_mae_c, label="climatology only")
    ax.plot(long_eval.lead_days, long_eval.persistence_mae_c, label="persistence")
    ax.plot(short_eval.lead_days, short_eval.published_mae_c, marker="o", label="published")
    ax.plot(short_eval.lead_days, short_eval.corrected_mae_c, marker="o", label="corrected")
    ax.set(xlabel="lead (days)", ylabel="MAE (C)", title="Max-temp error by lead, test window")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "04_mae_by_lead.png", dpi=110)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--city", default="bengaluru", choices=sorted(CITIES))
    p.add_argument("--db", default=str(ROOT / "data" / "warehouse.duckdb"))
    p.add_argument("--sprint", default="sprint-01")
    p.add_argument("--actuals-start", default="1995-01-01")
    p.add_argument("--published-start", default="2022-01-01")
    p.add_argument("--test-months", type=int, default=12)
    p.add_argument("--skip-fetch", action="store_true", help="reuse data already in the db")
    a = p.parse_args(argv)
    city, today = CITIES[a.city], date.today()
    out = ROOT / "results" / a.sprint
    for sub in ("metrics", "charts", "tables"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    Path(a.db).parent.mkdir(parents=True, exist_ok=True)
    con = warehouse.connect(a.db)
    log(
        f"[start] city={city.name} today={today} db={Path(a.db).name} "
        f"utc={datetime.now(UTC):%FT%TZ}"
    )
    if not a.skip_fetch:
        fetch_all(con, city, a.actuals_start, a.published_start, today)
    warehouse.build_models(con)
    for t in TABLES:
        snap = warehouse.snapshot(con, t, n=6)
        (out / "tables" / f"{t}.json").write_text(json.dumps(snap, indent=1), encoding="utf-8")
        log(f"[table] {t}: {snap['row_count']} rows")

    by_lead = q(
        con,
        "select * exclude (city) from mart_error_by_lead where city = ? "
        "order by variable, lead_days",
        [city.name],
    )
    by_lead.to_csv(out / "metrics" / "02_published_error_by_lead.csv", index=False)
    worst = q(
        con,
        "select date, lead_days, variable, forecast_c, actual_c, round(error_c, 1) "
        "as error_c from mart_forecast_error where city = ? and lead_days = 1 "
        "order by abs(error_c) desc, date desc limit 12",
        [city.name],
    )
    worst.to_csv(out / "metrics" / "03_worst_day_ahead_misses.csv", index=False)

    test_start = pd.Timestamp(today) - pd.DateOffset(months=a.test_months)
    log(f"[split] train < {test_start.date()} <= test")
    pairs_all = q(
        con,
        "select date, lead_days, variable, forecast_c, actual_c "
        "from mart_forecast_error where city = ?",
        [city.name],
    )
    pairs_all["date"] = pd.to_datetime(pairs_all["date"])
    summary, outlook, short_tests = {}, {}, {}
    for var in VARIABLES:
        actual = daily_series(con, city.name, var)
        pairs = pairs_all[pairs_all.variable == var].drop(columns="variable")
        long_eval, clim, _, _ = evaluate_long(actual, test_start)
        short_eval, short_test = evaluate_short(pairs, actual, clim, test_start)
        short_eval.to_csv(out / "metrics" / f"04_short_range_eval_{var}.csv", index=False)
        long_eval.to_csv(out / "metrics" / f"05_long_range_eval_{var}.csv", index=False)
        outlook[var] = build_outlook(con, city.name, var, actual, pairs, pd.Timestamp(today))
        short_tests[var] = short_test
        summary[var] = {"short": short_eval, "long": long_eval}
        log(
            f"[eval {var}] short-range lead1 published MAE "
            f"{short_eval.published_mae_c.iloc[0]} -> corrected "
            f"{short_eval.corrected_mae_c.iloc[0]}"
            f"; long-range lead30 model {long_eval.model_mae_c.iloc[-1]} vs clim "
            f"{long_eval.climatology_mae_c.iloc[-1]}"
        )

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
    table.to_csv(out / "metrics" / "01_outlook_next_30_days.csv", index=False)
    charts(
        out / "charts",
        con,
        city.name,
        outlook,
        short_tests["tmax"],
        summary["tmax"]["short"],
        summary["tmax"]["long"],
    )
    write_meta(out, con, city, today, test_start, by_lead, summary, a)
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
    return (
        f"{label}: kept the published forecast at lead {_leads(raw)} (no correction beat it in "
        f"CV); correction lowered error at {helped_txt}; {worst_txt}. The p10-p90 range held the "
        f"actual value on {cov.min():.1f}% to {cov.max():.1f}% of days (target 80%)."
    )


def write_meta(out: Path, con, city, today, test_start, by_lead, summary, a) -> None:
    """meta.json for the results page. Findings are built from measured numbers only."""
    tmax = by_lead[by_lead.variable == "tmax"].set_index("lead_days")
    rng = q(
        con,
        "select min(date), max(date), count(*) from mart_forecast_error "
        "where city = ? and variable = 'tmax' and lead_days = 1",
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
    findings = [
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
        "title": f"{a.sprint}: forecast error audit and 7/30-day outlook ({city.name})",
        "goal": "Measure how far published forecasts drift from what happened, then forecast the "
        "next week (published forecast, corrected only where CV shows it helps) and next month "
        "(climatology + decaying anomaly), each with a measured p10-p90 range.",
        "pattern": "batch ELT: raw -> staging -> marts (DuckDB) + per-lead MOS",
        "findings": findings,
        "commands": ["make test", "make run", "make results"],
        "scripts": sorted(
            str(p.relative_to(ROOT)).replace("\\", "/")
            for p in [
                *(ROOT / "sql").rglob("*.sql"),
                *(ROOT / "src").rglob("*.py"),
                *(ROOT / "scripts").glob("*.py"),
            ]
        ),
        "table_order": TABLES,
        "captions": {
            "01_outlook_next_30_days.csv": {
                "title": f"Outlook from {today}: next 30 days",
                "note": "Range = p10-p90, aiming for 8 in 10 days inside. Measured on the test "
                f"window it held: {cov_txt}. Days 1-7 use the published forecast, corrected "
                "where CV showed it helps. Days 8-30 are climatology plus a decaying anomaly, "
                "because no archived forecasts past 7 days exist to check the published "
                "8-16 day values (shown as published_* for reference).",
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
                "last_365d_only_mae_c = ablation trained on the final year only.",
            },
            "04_short_range_eval_tmin.csv": {
                "title": "Next-week model vs baselines: min temp",
                "note": "",
            },
            "05_long_range_eval_tmax.csv": {
                "title": "Next-month model vs baselines on the test window: max temp",
                "note": "anomaly_kept = share of today's anomaly carried to that lead.",
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
        ],
        "provenance": {
            "run_utc": f"{datetime.now(UTC):%FT%TZ}",
            "city": city.__dict__,
            "test_start": str(test_start.date()),
            "args": vars(a),
            "python": platform.python_version(),
            "duckdb": duckdb.__version__,
            "pandas": pd.__version__,
            "sklearn": sklearn.__version__,
        },
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
