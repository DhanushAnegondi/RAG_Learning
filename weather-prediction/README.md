# weatherwise

How wrong are published weather forecasts where you live, and what should you actually plan
around for the next week and month?

weatherwise pulls real data from Open-Meteo (no API key), stores it in DuckDB, measures the gap
between what was forecast and what happened (by how many days ahead it was forecast), and
produces a 7-day and 30-day outlook where every value comes with a measured p10-p90 range:
"8 in 10 days land inside this range", checked on a held-out year.

Results for every sprint, with tables, terminal output, charts and the architecture diagram:
open `results/index.html` (generated, never hand-edited).

## Data

| Source | What it is | Used as |
|---|---|---|
| Open-Meteo archive (ERA5) | Reanalysis daily max/min, 1995 to yesterday | what actually happened |
| Open-Meteo previous-runs | Hourly forecasts as issued 1-7 days before, 2022 onward | what was predicted |
| Open-Meteo forecast | Live 16-day forecast | input to the outlook |

## Method

- **Error audit (SQL).** Hourly published forecasts become daily max/min (24-hour days only),
  are joined to actuals, and summarised per lead: bias, MAE, p10/p90 error, share of days off by
  2 C and 3 C, worst miss. `sql/marts/`.
- **Next week (leads 1-7).** Per lead, three candidates compete: the published forecast as is,
  a linear correction, gradient boosting. 4-fold rolling-origin CV over the last training year
  picks one; a correction must beat the raw forecast by 2% or the raw forecast is kept. The range
  is the p10-p90 of out-of-fold residuals from that year.
- **Next month (leads 8-30).** No public model has day-level skill this far out, so the outlook
  is seasonal climatology (annual harmonics plus a warming trend) plus today's anomaly decayed by
  a per-lead factor learned from 30 years. Range from backtest residuals.
- **Evaluation.** Everything is fit on data before the test window (last 12 months) and compared
  with climatology and persistence on the same days.

## Run

```bash
make setup      # uv venv + deps + headless Chromium for rendering
make test       # offline pytest -> results/sprint-01/run/green.out
make check      # ruff, ruff format, sqlfluff
make mutate     # break the code on purpose; every mutation must fail a test
make run        # fetch real data, build SQL, evaluate, forecast (about 1 minute)
make diagram    # stack-diagram as-built -> results/sprint-01/architecture.png
make results    # results/index.html + results/index.png
```

Another city: `.venv/Scripts/python scripts/run_pipeline.py --city chennai` (cities in
`src/weatherwise/config.py`; add a row for your own).

## Layout

```
sql/raw|staging|marts   all SQL, run by warehouse.py in order
src/weatherwise/        ingest, warehouse, models, pipeline, report
scripts/                entry points (one per make target)
tests/                  offline tests + CATALOG.md
results/<sprint>/       captured outputs; results/index.html covers all sprints
ledger/                 session logs, decisions, errors, lessons
```
