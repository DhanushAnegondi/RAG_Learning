"""Break the code on purpose; each mutation must make at least one test fail. Restores files.

Run: .venv/Scripts/python scripts/mutation_check.py  (make mutate)
KILLED means pytest exited 1 (a test failed) and names the first failing test. Test files run
in an order that puts the likeliest killers first (test_order); a survivor has faced them all. A crash
(exit 2+, e.g. a syntax error) counts as CRASHED, not as a kill. A mutant of a migration file
only exists once the migration runs, so the test database's schema is dropped before such a
mutant and again after it.
"""

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
M = "src/weatherwise/models.py"
P = "src/weatherwise/pipeline.py"
I = "src/weatherwise/ingest.py"  # noqa: E741
R = "src/weatherwise/report.py"
OB = "src/weatherwise/observations.py"
WH = "src/weatherwise/warehouse.py"
S = "src/weatherwise/site.py"
D = "src/weatherwise/deep.py"
MART = "sql/marts/01_mart_forecast_error.sql"
LEAD = "sql/marts/02_mart_error_by_lead.sql"
MUTATIONS = [  # (file, original, mutant, what it simulates); the full suite runs each time
    (
        MART,
        "long_form.forecast_c - long_form.actual_c as error_c",
        "long_form.actual_c - long_form.forecast_c as error_c",
        "error sign flipped",
    ),
    (
        "sql/staging/stg_published_daily.sql",
        "where by_day.n_hours = 24",
        "where by_day.n_hours > 0",
        "partial days kept",
    ),
    (MART, "inner join actual", "left join actual", "inner join became left join"),
    (
        MART,
        "on published.city = actual.city and published.date = actual.date",
        "on published.date = actual.date",
        "join key loses city",
    ),
    (
        WH,
        'like = f"like {target} including defaults including indexes"',
        'like = f"like {target} including defaults"',
        "duplicate keys in a batch accepted",
    ),
    (
        "sql/raw/load_actual_daily.sql",
        "        tmax_c = excluded.tmax_c,\n",
        "",
        "corrected max not replaced on reload",
    ),
    (
        WH,
        '    with con.transaction():\n        con.execute("drop table if exists incoming")',
        '    if True:\n        con.execute("drop table if exists incoming")',
        "load is not one transaction",
    ),
    (
        WH,
        'if not name.endswith("_test"):',
        "if False:",
        "reset allowed on the real database",
    ),
    (
        WH,
        '        if path.name in done or path.name.startswith("000_"):',
        '        if path.name.startswith("000_"):',
        "migrations re-applied",
    ),
    (
        "sql/checks/checksum.sql",
        "cast(row(city, date, tmax_c, tmin_c, precip_mm) as text)",
        "cast(row(city, date) as text)",
        "checksum blind to values",
    ),
    (
        "sql/migrations/001_tables.sql",
        "primary key (city, model, issued_on, date)",
        "primary key (city, model, date)",
        "live forecast key loses issued_on",
    ),
    (
        "sql/staging/stg_published_daily.sql",
        "group by source.city, source.model, source.lead_days, cast(source.ts_local as date)",
        "group by source.city, source.model, source.lead_days * 0, cast(source.ts_local as date)",
        "leads merged in staging grain",
    ),
    (
        "sql/staging/stg_actual_daily.sql",
        "    source.tmax_c between -60 and 60\n",
        "    true\n",
        "null or impossible max reaches the marts",
    ),
    (
        LEAD,
        "sqrt(avg(errors.error_c * errors.error_c))",
        "avg(abs(errors.error_c))",
        "rmse computed as mae",
    ),
    (
        LEAD,
        "when abs(errors.error_c) >= 3",
        "when abs(errors.error_c) > 3",
        "share_off_3c boundary",
    ),
    (I, '"lead_days": lead,', '"lead_days": lead + 1,', "lead labelled off by one"),
    (
        I,
        "transient = resp.status_code >= 500 or resp.status_code == 429",
        "transient = resp.status_code >= 500",
        "429 not retried",
    ),
    (
        I,
        "except requests.exceptions.JSONDecodeError:",
        "except ZeroDivisionError:",
        "non-JSON 5xx not retried",
    ),
    (
        I,
        '"timezone": city.timezone',
        '"tz_unused": city.timezone',
        "timezone dropped from requests",
    ),
    (
        M,
        'if maes[best] > maes["raw"] * (1 - self.min_gain):',
        "if False:",
        "selection margin removed",
    ),
    (
        M,
        'return df[df["date"] < test_start], df[df["date"] >= test_start]',
        'return df[df["date"] <= test_start], df[df["date"] >= test_start]',
        "test start date leaks into train",
    ),
    (
        M,
        "for k in range(self.n_folds, 0, -1):",
        "for k in range(self.n_folds * 3, 0, -1):",
        "band built from stale years",
    ),
    (
        M,
        "(min(float(lo), 0.0), max(float(hi), 0.0))",
        "(float(lo), float(hi))",
        "band clamp removed",
    ),
    (
        M,
        "return anom.rolling(window, min_periods=window).mean()",
        "return anom.rolling(window, min_periods=1).mean()",
        "partial anomaly windows",
    ),
    (M, "if age > max_age_days:", "if False:", "stale anomaly accepted"),
    (M, "    if missing:", "    if False:", "missing published days accepted"),
    (
        M,
        'short = out["lead_days"] <= short_leads',
        'short = out["lead_days"] < short_leads',
        "day 7 not corrected",
    ),
    (
        M,
        "base + coef[:horizon] * recent_anomaly",
        "base + np.roll(coef[:horizon], 1) * recent_anomaly",
        "decay coefficient misaligned",
    ),
    (P, "fit_part = actual.iloc[:-365]", "fit_part = actual", "long-range bands in-sample"),
    (
        P,
        "train = actual[actual.index < test_start]",
        "train = actual",
        "long-range fit sees test window",
    ),
    (P, "if start > stop:", "if False:", "inverted range on 1 January"),
    (
        R,
        "f\"{escape(o.read_text(encoding='utf-8'))}</pre></details>\"",
        "f\"{o.read_text(encoding='utf-8')}</pre></details>\"",
        "terminal output not escaped",
    ),
    (R, "reverse=True,", "reverse=False,", "sprints oldest first"),
    # ---- sprint 02 ----
    (
        "sql/migrations/001_tables.sql",
        "primary key (city, model, ts_local, lead_days)",
        "primary key (city, ts_local, lead_days)",
        "weather model drops out of the key",
    ),
    (
        "sql/migrations/001_tables.sql",
        "primary key (city, kind, issued_on, date, variable)",
        "primary key (city, issued_on, date, variable)",
        "hindcast can overwrite a live forecast",
    ),
    (
        "sql/raw/load_forecast_log.sql",
        "    kind = 'hindcast'\n    and city in (",
        "    kind <> 'x'\n    and city in (",
        "replay deletes live forecasts",
    ),
    (MART, "where model = 'best_match'", "where true", "other models leak into published error"),
    (
        "sql/staging/stg_published_daily.sql",
        "where temp_c between -60 and 60",
        "where true",
        "impossible forecast hour kept",
    ),
    (
        "sql/staging/stg_actual_daily.sql",
        "    and source.tmax_c >= source.tmin_c",
        "",
        "max below min accepted",
    ),
    (
        "sql/staging/stg_actual_daily.sql",
        "    and source.tmin_c between -60 and 60\n",
        "",
        "impossible min accepted",
    ),
    (
        "sql/marts/03_mart_model_pairs.sql",
        "when published.model = 'gfs_seamless' then published.tmax_c end) as tmax_gfs",
        "when published.model = 'ecmwf_ifs025' then published.tmax_c end) as tmax_gfs",
        "gfs column filled from ecmwf",
    ),
    (
        "sql/marts/04_mart_data_quality.sql",
        "actual_raw.raw_rows - actual_ok.usable_days as rejected_days",
        "0 as rejected_days",
        "rejected days not counted",
    ),
    (
        "sql/marts/05_mart_verification.sql",
        "order by case when log_forecast.kind = 'live' then 0 else 1 end",
        "order by case when log_forecast.kind = 'live' then 1 else 0 end",
        "hindcast preferred over live",
    ),
    (
        "sql/marts/05_mart_verification.sql",
        "ranked.pred_c - observed.observed_c as our_error_c",
        "observed.observed_c - ranked.pred_c as our_error_c",
        "verification error sign flipped",
    ),
    (
        "sql/marts/05_mart_verification.sql",
        "(observed.observed_c between ranked.lo_c and ranked.hi_c) as inside_range",
        "(observed.observed_c >= ranked.lo_c) as inside_range",
        "inside-range ignores the upper edge",
    ),
    (
        "sql/site/outlook.sql",
        "select max(newest.issued_on)",
        "select min(newest.issued_on)",
        "outlook shows the oldest forecast",
    ),
    (OB, "(value - 32) * 5 / 9", "(value - 32) * 9 / 5", "fahrenheit conversion wrong"),
    (OB, "    if day > today:", "    if False:", "future entry accepted"),
    (
        OB,
        "tmax_c is not None and tmin_c is not None and tmax_c < tmin_c",
        "False",
        "high below low accepted",
    ),
    (
        OB,
        "if v is not None and not LIMIT_C[0] <= v <= LIMIT_C[1]:",
        "if False:",
        "impossible entry accepted",
    ),
    (
        WH,
        'df = df.assign(model="best_match")',
        'df = df.assign(model="gfs_seamless")',
        "default model mislabelled",
    ),
    (
        WH,
        "select * from log_forecast where kind = 'live'",
        "select * from log_forecast",
        "backup includes hindcasts",
    ),
    (
        I,
        'block.get(f"{src}_{model}"',
        'block.get(f"{src}_best_match"',
        "every model reads best_match",
    ),
    (M, ".mean().shift(int(lead) + 1)", ".mean().shift(int(lead))", "recent bias peeks one day"),
    (
        M,
        'd["forecast_c"] - d["bias_recent"].fillna(0.0)',
        'd["forecast_c"] + d["bias_recent"].fillna(0.0)',
        "drift adds the bias",
    ),
    (
        M,
        "return lambda d: np.nanmean(_model_matrix(d), axis=1)",
        "return lambda d: np.nan_to_num(_model_matrix(d)).mean(axis=1)",
        "missing model counted as zero",
    ),
    (
        M,
        "keep = ~np.isnan(x).all(axis=0)",
        "keep = np.ones(x.shape[1], dtype=bool)",
        "all-NaN model column kept",
    ),
    (M, ".ffill().shift(lead + 1)", ".ffill().shift(lead)", "adaptive range peeks one day"),
    (
        M,
        'out.loc[g.index, "lo_c"] = pred + np.minimum(edges["lo_c"], 0.0)',
        'out.loc[g.index, "lo_c"] = pred + edges["lo_c"]',
        "adaptive range can exclude the forecast",
    ),
    (
        M,
        'out["pred_c"] = base + coef[:horizon] * recent_anomaly if long_pred is None else long_pred',
        'out["pred_c"] = base + coef[:horizon] * recent_anomaly',
        "long-range override ignored",
    ),
    (
        P,
        'val_mae["decay"] * (1 - min_gain)',
        'val_mae["decay"] * (1 + min_gain)',
        "LSTM wins on a sliver",
    ),
    (
        P,
        "return now.astimezone(ZoneInfo(city.timezone)).date()",
        "return now.date()",
        "today from UTC, not the city",
    ),
    (
        P,
        'out["date"] - pd.to_timedelta(out["lead_days"], unit="D")',
        'out["date"] + pd.to_timedelta(out["lead_days"], unit="D")',
        "issue day computed forwards",
    ),
    (
        P,
        "train = actual[actual.index < test_start]\n    chosen, resid",
        "train = actual\n    chosen, resid",
        "long-range selection sees test window",
    ),
    (
        S,
        "raise HTTPException(400, str(exc)) from None",
        'return {"checks": []}',
        "bad entry reported as success",
    ),
    (D, "self.net.load_state_dict(best_state)", "pass", "LSTM keeps the last epoch, not the best"),
    # ---- sprint 03 reviews ----
    (
        "sql/raw/load_forecast_log.sql",
        "    where log_forecast.kind = 'hindcast';",
        ";",
        "same-day rerun rewrites a live forecast",
    ),
    (
        "sql/raw/load_actual_daily.sql",
        "is distinct from (excluded.tmax_c, excluded.tmin_c, excluded.precip_mm)",
        "is not null",
        "identical reload rewrites every row",
    ),
    (
        "sql/checks/checksum.sql",
        "cast(row(city, model, ts_local, lead_days, temp_c) as text)",
        "cast(row(city, model, ts_local, lead_days) as text)",
        "checksum blind to forecast values",
    ),
    (WH, "    assert_test_database(con.execute", "    str(con.execute", "reset skips its guard"),
    (
        WH,
        '        for path in sorted(Path(directory or SQL_DIR / "migrations").glob("*.sql")):',
        '        for path in sorted(Path(directory or SQL_DIR / "migrations").glob("*.sql"), reverse=True):',
        "migrations run newest first",
    ),
    (M, ".mean().shift(int(lead) + 1)", ".mean().shift(int(lead) + 2)", "recent bias a day late"),
    (M, ".ffill().shift(lead + 1)", ".ffill().shift(lead + 2)", "adaptive range a day late"),
    (
        M,
        "roll = known.dropna().rolling(window, min_periods=min_n)",
        "roll = known.dropna().rolling(window * 2, min_periods=min_n)",
        "adaptive range window doubled",
    ),
    (
        P,
        'replay = long["bt"].assign(lead_days=long["bt"]["lead_days"] - 1)',
        'replay = long["bt"].assign(lead_days=long["bt"]["lead_days"])',
        "long replay filed a day early",
    ),
    (
        P,
        'pred_c=(out["decay"]["pred_c"] + out["lstm"]["pred_c"]) / 2',
        'pred_c=out["lstm"]["pred_c"]',
        "mix is not the average",
    ),
    (
        S,
        "                clean[k] = v.isoformat()  # dates arrive",
        "                clean[k] = v.date().isoformat()  # dates arrive",
        "timestamps lose their time",
    ),
    (
        S,
        '        return state["pool"].connection()',
        '        return state["pool"].getconn()',
        "request keeps its pooled connection",
    ),
    (OB, 'if note and "\\x00" in note:', "if False:", "unstorable note reaches the driver"),
]


MODEL_TESTS = ["test_sprint2_models.py", "test_models.py", "test_sprint3_review.py"]


def test_order(rel: str) -> list[str]:
    """Every test file, the ones most likely to notice a change in `rel` first. The whole suite
    still runs before a mutant counts as SURVIVED; with -x a kill just comes sooner."""
    names = sorted(p.name for p in (ROOT / "tests").glob("test_*.py"))
    model_code = rel in (M, P, D)
    first = [n for n in names if (n in MODEL_TESTS) == model_code]
    return [f"tests/{n}" for n in first + [n for n in names if n not in first]]


def drop_test_schema() -> None:
    """Empty the test database completely; the next test connection migrates it again."""
    url = os.environ.get(
        "WEATHERWISE_TEST_DATABASE_URL",
        "postgresql://weatherwise:weatherwise@127.0.0.1:15480/weatherwise_test",
    )
    with psycopg.connect(url, autocommit=True) as con:
        name = con.execute("select current_database()").fetchall()[0][0]
        if not name.endswith("_test"):
            raise RuntimeError(f"refusing to drop the schema of {name!r}")
        con.execute("drop schema public cascade")
        con.execute("create schema public")


def main() -> int:
    print(f"# mutation run {datetime.now(UTC):%FT%TZ}; KILLED = a test failed (exit 1)")
    bad = 0
    for rel, old, new, what in MUTATIONS:
        path = ROOT / rel
        src = path.read_text(encoding="utf-8")
        if old not in src:
            print(f"MISSING  {what}: pattern not found in {rel}")
            bad += 1
            continue
        path.write_text(src.replace(old, new, 1), encoding="utf-8")
        migration = rel.startswith("sql/migrations/")
        if migration:
            drop_test_schema()
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-x", "-rf", "--tb=no", *test_order(rel)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
        finally:
            path.write_text(src, encoding="utf-8")
            if migration:
                drop_test_schema()
        killer = next(
            (ln.split()[1] for ln in r.stdout.splitlines() if ln.startswith("FAILED")), "-"
        )
        status = {0: "SURVIVED", 1: "KILLED  "}.get(r.returncode, "CRASHED ")
        bad += r.returncode != 1
        print(f"{status} {what:36s} by {killer}")
    print(f"\n{len(MUTATIONS) - bad}/{len(MUTATIONS)} mutations killed by a failing test")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
