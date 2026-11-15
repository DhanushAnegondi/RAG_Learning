# weatherwise

**The forecast said 28. It hit 31. How often does that happen, and what should you plan for instead?**

weatherwise answers that with real data. It collects what weather models forecast and what
actually happened, measures the gap, corrects the forecast where the data proves it can, and
gives every number a "likely range". Then it lets you check it yourself: type in the temperature
you saw on any day and the site shows what was forecast for that day and how far off it was.

Default city: **Torrance, California** (shown in °F; other cities are one config line).

![Forecast tab](results/sprint-03/site/forecast.png)

---

## Contents

1. [What it found for Torrance](#what-it-found-for-torrance)
2. [How the site works](#how-the-site-works)
3. [How the forecast is made](#how-the-forecast-is-made)
4. [Run it](#run-it)
5. [Daily use](#daily-use)
6. [How it is tested](#how-it-is-tested)
7. [Honest limits](#honest-limits)
8. [Repo layout](#repo-layout)
9. [Sprints](#sprints)

---

## What it found for Torrance

All numbers are measured, from `results/sprint-03/metrics/`. "Miss" means the average distance
between forecast and outcome (mean absolute error). 1 °C = 1.8 °F.

**How wrong the published forecast has been (2022 to today, 1,756 days)**

| | 1 day ahead | 7 days ahead |
|---|---|---|
| Daily high, average miss | 1.2 °C (2.2 °F) | 1.7 °C (3.1 °F) |
| Daily high, days off by 3 °C (5.4 °F) or more | 8% | 16% |
| Daily high, worst miss | 7.4 °C (13 °F) | 12.1 °C (22 °F) |
| Daily low, average miss | 2.3 °C (4.2 °F) | 3.3 °C (6.0 °F) |

So "forecast 28, got 31" is not rare: about one day in twelve, even for tomorrow's high.

**Does weatherwise do better? Checked on the last 12 months, which the models never saw**

| Days ahead | High: published | High: weatherwise | Low: published | Low: weatherwise |
|---|---|---|---|---|
| 1 | 1.29 °C | **1.14 °C** | 1.53 °C | **0.70 °C** |
| 2 | 1.27 | **1.11** | 3.16 | **0.76** |
| 3 | 1.45 | **1.08** | 3.13 | **0.84** |
| 4 | 1.50 | **1.21** | 3.10 | **0.87** |
| 5 | 1.65 | **1.39** | 3.09 | **1.00** |
| 6 | 1.84 | **1.58** | 3.08 | **1.15** |
| 7 | 2.04 | **1.77** | 2.97 | **1.28** |

- Highs improve by 12 to 25%. Lows improve by 54 to 76%.
- The big gain on lows has a plain cause: from two days out, the published forecast for
  Torrance runs about 3 °C too warm at night. The correction learns that and removes it.
- **Days 8 to 30:** no model, public or mine, forecasts individual days that far out. The
  30-day line is the seasonal normal nudged by how unusual the last few days were. For highs it
  is only as good as the plain seasonal average (2.8 °C miss). For lows it is a little better
  (2.0 vs 2.3 °C).
- **The likely range** is meant to hold the real value 8 times in 10. Measured: 73 to 80% for
  days 1 to 7, and 67 to 74% for days 8 to 30. It runs slightly narrow, and the page says so.

---

## How the site works

Start it with `make site` and open <http://localhost:8000>. Five tabs:

### 1. Forecast
![Forecast tab](results/sprint-03/site/forecast.png)

- **Seven cards**, one per day: the forecast high and low, the likely range for each, and the
  published forecast underneath for comparison. The small tag says how that number was made.
- **Two 30-day charts** (high, low): blue line = weatherwise, dashed orange = published,
  shaded band = likely range. Hover for exact values.
- **°F / °C** switch at the top. **Update forecast** fetches today's data and re-forecasts
  (a few minutes).

### 2. Check a day
![Check a day tab](results/sprint-03/site/check.png)

This is the part you asked for.

1. Pick the day, type the high and/or low you saw, choose °F or °C, press **Save and compare**.
2. The site shows a verdict in one sentence: what was forecast the day before, how far off it
   was, whether your reading fell inside the likely range, and whether weatherwise or the
   published forecast was closer.
3. Below that, a table with every forecast made for that day: 1 day before, 2 days before, and
   so on back to 30 days before.

Two kinds of rows appear:

| Kind | What it is |
|---|---|
| **Issued live** | The first forecast the site made on that date. Later runs the same day cannot change it. |
| **Replay** | What the models would have said, re-run over the last 12 months, which they were not trained on. This is why you can check a day from last month on your first visit. |

Typing the same day again edits your entry. Your entries are also saved to
`data/user_observations.csv`, so they survive a database rebuild.

### 3. Scoreboard
![Scoreboard tab](results/sprint-03/site/scoreboard.png)

Built only from days you entered: how many days you checked, weatherwise's average miss, the
published forecast's average miss on the same days, and how often your reading fell inside the
likely range. One more column, **your reading vs grid data**, shows whether your thermometer
runs steadily warmer or cooler than the dataset the models learn from. A steady gap is your
location, not a forecast error.

### 4. Track record
![Track record tab](results/sprint-03/site/record.png)

The evidence behind the tables above: average miss by days ahead, the last 120 days of
day-before forecasts against what happened, and a leaderboard of every method at every lead with
the chosen one highlighted.

### 5. Data
![Data tab](results/sprint-03/site/data.png)

A health check (rows received, usable days, rejected days, missing days per source) and every
table in the database, raw to final, with its columns, row count and first rows.

---

## How the forecast is made

![Architecture](results/sprint-03/architecture.png)

**1. Collect** (Open-Meteo, free, no API key)

| Source | What | Used as |
|---|---|---|
| Historical archive | Daily high and low, 1995 to yesterday | what happened |
| Previous-runs archive | Hourly forecasts as issued 1 to 7 days earlier, from up to 4 weather models (two from 2022, two more from early 2024) | what was forecast |
| Forecast API | Today's 16-day forecast from the same 4 models | input to today's outlook |

**2. Store and clean** (Postgres, plain SQL files in `sql/`)

- Loads can be repeated safely: the same data loaded twice leaves the same rows.
- Cleaning rules reject impossible values (outside -60 to 60 °C), days where the high is below
  the low, and forecast days without all 24 hours. Rejected rows are listed, not hidden.

**3. Correct the next 7 days.** For each number of days ahead, six methods compete:

| Method | Idea |
|---|---|
| Published, as is | keep the forecast unchanged |
| Fixed correction | a constant adjustment by season (linear, or gradient boosting) |
| Recent-bias correction | subtract the forecast's average error over the last few weeks |
| Model average | the mean of the weather models |
| Blend | gradient boosting over all models, how much they disagree, and the recent bias |

The winner is chosen by a rolling test inside the training data and must beat the published
forecast by at least 2%, otherwise the published forecast is kept. For Torrance the blend won
almost everywhere.

**4. Days 8 to 30.** Seasonal normal (30 years, with the warming trend) plus an anomaly forecast.
Three candidates: a simple fading anomaly, an LSTM neural network, and their average. The choice
is made on a validation year.

**5. The likely range** comes from the last 120 misses that were known on the day the forecast
was made, so it widens when recent forecasts have been poor.

**6. Log everything.** Every forecast is stored with its issue date. That log is what the site
compares your readings against.

### Why no AI agent makes the forecast

A language model cannot lower a temperature error; arithmetic on measured errors can. So the
numbers come from the statistical models above. A LangGraph assistant that reads these tables
and answers planning questions is the next sprint (see [Sprints](#sprints)); it will explain the
numbers, never invent them.

---

## Run it

Needs: Docker Desktop, [uv](https://docs.astral.sh/uv/), `make` (Git Bash on Windows).

```bash
make setup      # Python environment and dependencies
make up         # start Postgres in Docker (127.0.0.1:15480)
make run        # fetch real data, load, train, forecast (about 5 minutes the first time)
make site       # open http://localhost:8000
```

Other commands:

```bash
make test       # 132 tests against a real Postgres test database
make check      # ruff + sqlfluff
make mutate     # break the code on purpose; every break must fail a test
make results    # rebuild results/index.html (every sprint, every table, every output)
make down       # stop Postgres (data is kept in a Docker volume)
```

Another city: `make run CITY=chennai`. Add your own in `src/weatherwise/config.py`.

Settings live in `.env` (copy `.env.example`). Nothing secret is in the repo.

---

## Daily use

1. Open the site. If the forecast date is not today, press **Update forecast**.
2. In the evening, or the next day, open **Check a day** and type what you saw.
3. After a couple of weeks the **Scoreboard** tells you, on your own readings, whether
   weatherwise or the published forecast has been closer.

The live forecasts are the fair test: the first one made each day is stored before the day
happens, and nothing can change it afterwards.

---

## How it is tested

- **Tests first.** Each test was seen failing before its code existed
  (`results/<sprint>/run/red*.out`), then passing. 132 tests, listed with the bug each one
  catches in [`tests/CATALOG.md`](tests/CATALOG.md).
- **Real database.** Tests run against Postgres, not a mock.
- **Mutation check.** A script breaks the code in 79 specific ways (flip a sign, drop a
  key column, let the model peek at the future). Each break must make a named test fail.
- **No peeking.** The last 12 months are never used to fit, choose or tune anything. Tests
  inject a +10 °C jump into that window and assert nothing learned from it.
- **Two independent reviews per sprint**, one of the code and one of the tests. Findings and
  fixes are in `results/<sprint>/review.md`.
- **Everything shown is generated.** [`results/index.html`](results/index.html) is built by a
  script from captured files: commands, terminal output, tables before and after, charts.

---

## Honest limits

- **Your thermometer is not the dataset.** "What happened" is a gridded analysis for the area
  around Torrance, not a station in your yard. Readings can sit a steady 1 to 3 °C away. The
  scoreboard reports that gap separately so it is not mistaken for forecast error.
- **One held-out year.** Differences under about 0.1 °C are noise.
- **Days 8 to 30 are a seasonal expectation with a range**, not a weather forecast.
- **The range runs a little narrow** (73 to 80% instead of 80%). For days 8 to 30 the band
  currently sits mostly above the line, because recent months ran warmer than the seasonal
  model expected.
- **The method list was revised once after seeing the held-out numbers** (the adaptive range and
  the averaged long-range candidate). From here on, the fair evidence is the live forecast log
  against your entries.
- **For Torrance, two of the four weather models are the same series**, so the blend really has
  three independent inputs.
- Temperature only. Rain is fetched but not modelled.

---

## Repo layout

```
docker-compose.yml       Postgres for local use
sql/migrations/          table definitions, applied in order
sql/raw/                 loaders (insert ... on conflict)
sql/staging/, sql/marts/ cleaning rules, forecast-vs-actual tables, verification views
sql/site/, sql/checks/   the site's queries, checksum and test reset
src/weatherwise/         ingest, warehouse, models, deep (LSTM), pipeline, observations, site, report
web/                     the site's page, script and styles
scripts/                 one entry point per make target
tests/                   tests and CATALOG.md
results/<sprint>/        captured outputs; results/index.html covers every sprint
docs/                    spec, tickets, project standards
data/                    CSV backups of your entries and the live forecast log
```

---

## Sprints

| Sprint | What | State |
|---|---|---|
| 01 | Forecast-error audit and first 7/30-day outlook (Bengaluru, DuckDB) | done |
| 02 | Torrance, four weather models, blend and recent-bias correction, LSTM, forecast log, site | built on DuckDB, frozen, carried into 03 |
| 03 | Port to Postgres in Docker: migrations, safe reloads, same numbers | this sprint |
| 04 | LangGraph planning assistant: typed read-only SQL tools, checkpoints, memory, logged tool calls | planned |
| 05 | Operations: daily run, drift detection with approval, scored question set, fault injection | planned |

Plan and acceptance criteria: [`docs/spec-postgres-agent.md`](docs/spec-postgres-agent.md).
