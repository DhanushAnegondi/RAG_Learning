"""Break the code on purpose; each mutation must make at least one test fail. Restores files.

Run: .venv/Scripts/python scripts/mutation_check.py  (make mutate)
KILLED means pytest exited 1 (a test failed) and names the first failing test. A crash
(exit 2+, e.g. a syntax error) counts as CRASHED, not as a kill.
"""

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = "src/weatherwise/models.py"
P = "src/weatherwise/pipeline.py"
I = "src/weatherwise/ingest.py"  # noqa: E741
R = "src/weatherwise/report.py"
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
        "sql/raw/load_actual_daily.sql",
        "having count(*) > 1",
        "having count(*) > 99",
        "actual_daily duplicate guard off",
    ),
    (
        "sql/raw/load_published_hourly.sql",
        "having count(*) > 1",
        "having count(*) > 99",
        "published_hourly duplicate guard off",
    ),
    (
        "sql/raw/00_create_raw.sql",
        "primary key (city, issued_on, date)",
        "primary key (city, date)",
        "live forecast key loses issued_on",
    ),
    (
        "sql/staging/stg_published_daily.sql",
        "group by source.city, source.lead_days, cast(source.ts_local as date)",
        "group by source.city, source.lead_days * 0, cast(source.ts_local as date)",
        "leads merged in staging grain",
    ),
    (
        "sql/staging/stg_actual_daily.sql",
        "where source.tmax_c is not null and source.tmin_c is not null",
        "where true",
        "null actuals reach the marts",
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
]


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
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-x", "-rf", "--tb=no", "tests"],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
        finally:
            path.write_text(src, encoding="utf-8")
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
