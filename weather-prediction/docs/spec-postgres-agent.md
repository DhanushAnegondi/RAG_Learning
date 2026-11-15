# Feature: weatherwise on Postgres with a LangGraph planning agent

Tier and reason: High. Persistent schema, migrations, agent checkpoints and long-term memory in a
server database; a wrong migration or a leaky tool is expensive to undo. Tracked spec,
dependency-ordered tickets (`docs/tickets/`), independent review of code and of tests per sprint.

## Goal and first useful demonstration
User: one person planning around the weather in Torrance, California.
Problem: published forecasts miss, and the miss grows with lead time ("forecast 28, got 30 or 33").
Outcome: a site and an assistant that say what is forecast for the next week and month, how far
off such forecasts usually are, and whether a past forecast matched what the user saw.
First useful demonstration (sprint 03): `make up && make run` loads real Torrance data into
Postgres, and the existing site serves the same pages from it.

## Scope and exclusions
In scope, in order:
- Sprint 03, warehouse port: Postgres 18 in Docker Compose, SQL migrations, idempotent loads,
  the existing models, forecast log and site running on it.
- Sprint 04, agent: LangGraph assistant with typed read-only SQL tools, checkpoints, memory,
  logged tool calls.
- Sprint 05, operations: daily run, drift detection with a human approval gate, scored question
  set, fault injection.
Out of scope: rain and wind models, hosting outside this machine, user accounts, any forecast
produced by the language model (it only reads and explains what the statistical models wrote).

## Global Constraints
- Mandatory project standards (`docs/agents/project-standards.md`): source in the repo, tests seen
  failing first and tracked in `tests/CATALOG.md`, mutation check, ponytail review of code and of
  tests, stack-diagram, generated `results/index.html`.
- Real data only outside tests. Tests use a real Postgres (the Compose service, database
  `weatherwise_test`), never a mocked database. Agent tests run offline with a scripted fake model.
- Storage is Celsius; Fahrenheit only at the site and agent boundary.
- The test window is never used for fitting, selection or range calibration.
- No secrets in the repo. `ANTHROPIC_API_KEY` and the database password come from `.env`
  (git-ignored); `.env.example` documents the names. Nothing reads or prints the key.
- Windows host, Docker Desktop, Postgres bound to 127.0.0.1 only.

## Alignment decisions and open questions
Decided by the user (2026-11-14):
- Postgres, not DuckDB. Port what exists; do not restart.
- LangGraph/LangChain is a first-class part. The statistical models make the numbers.
- The agent calls Claude through the API (`WEATHERWISE_MODEL`, default `claude-opus-5-5`).
- Sprint 02 on DuckDB is frozen as measured and carried into the port, where it is reviewed once.
- City: Torrance (other cities stay configurable).
Open:
- Whether to add a global rule requiring a server database instead of an embedded one. The
  user's call; not edited by any session.
- Agent cost ceiling per day (default proposed: stop after 200 model calls per thread).

## Approaches and research
- Driver: psycopg 3 with `psycopg_pool`. LangGraph's Postgres checkpointer and store use the
  same driver, so one pool config serves warehouse, site and agent.
- Migrations: numbered SQL files in `sql/migrations/`, applied in order by a 40-line runner that
  records each in `app.schema_migration`. Rejected: Alembic (hides SQL in Python, against the
  source-in-repo rule) and DuckDB-over-Postgres (not what was asked).
- Loads: `copy` into a temp table, then `insert ... on conflict (key) do update`. A duplicate key
  inside one batch raises in Postgres ("cannot affect row a second time"), which replaces the
  DuckDB `error()` guard.
- Layout: one schema with table-name prefixes `raw_`, `stg_` (views), `mart_`, `log_`, `app_`
  (as built in sprint 03, so existing queries and tests stay valid); a separate `agent` schema
  for the tool-call log and LangGraph's own tables.
- Agent shape: one `StateGraph` (route -> call model -> run tools -> answer), not a prebuilt
  ReAct helper, so retries, timeouts, logging and the approval interrupt are explicit nodes.
- Read-only by construction: tools run as database role `weatherwise_reader` (select on marts
  and app views only). The agent has no tool that writes forecasts or runs arbitrary SQL.
Versions are pinned in `pyproject.toml` at implementation time from the installed releases.

## Interfaces and failure behavior
- `make up` / `make down`: Compose service `db` (postgres:18), healthcheck, named volume.
- `make migrate`: applies pending migrations; rerun is a no-op; a failed migration rolls back.
- `warehouse.load(conn, table, df)`: upsert, returns row count; rerun gives the same checksum.
- Site API: unchanged routes and payloads (existing tests are the contract).
- Agent tools (sprint 04), each a parameterized SQL file in `sql/agent/` with a typed schema:
  `get_outlook`, `get_forecast_error_by_lead`, `check_day`, `get_scoreboard`,
  `get_data_health`, `remember_preference`, `recall_preferences`.
- Tool call record: `agent.tool_call(thread_id, call_id, tool, args, status, rows, ms, error,
  started_at)`; `call_id` is unique, so a replay after a crash does not run a tool twice.
- Failure behavior: tool timeout 10 s and 2 retries with backoff; database down -> the agent says
  the data is unavailable, it does not guess; model call failure -> retried, then a clear error.
- Recovery: a killed process resumes a thread from its last checkpoint.
- Rollback: the DuckDB code stays on branch `add/weather-prediction` at commit 3ba2cd8 plus the
  frozen sprint-02 working tree; the port lands as its own commits.

## Current sprint
Sprint 03 tickets, in dependency order (`docs/tickets/sprint-03.md`): T1 compose and config,
T2 migrations and runner, T3 loaders, T4 staging and marts SQL in the Postgres dialect,
T5 pipeline and site on the new warehouse, T6 real run for Torrance, T7 browser check of the
site, T8 mutation check, two reviews, results page, diagram, README.
First runnable slice: T1 + T2 (`make up && make migrate` creates every table, twice, safely).

## Acceptance criteria and Review Focus
Sprint 03:
- Every existing behavior test passes against Postgres; no test is deleted to make that true.
- Loading the same data twice leaves row counts and a content checksum unchanged.
- Published-forecast error by lead, model leaderboard and outlook match the frozen DuckDB run
  for the same day within rounding (same data, same models).
- The site works in a browser: forecast, entry in F, comparison, scoreboard, data pages.
Review focus: dialect differences that change results silently (percentile, date arithmetic,
integer division, null ordering), transaction boundaries in loads, the reader role's grants.
Sprint 04:
- A killed run resumes from its checkpoint without repeating a completed tool call.
- A preference stated in one thread is recalled in a new thread.
- Every tool call appears in `agent.tool_call`; a write attempt through the reader role fails.
- The agent refuses to state a number that is not in a tool result (scored question set).
Sprint 05:
- Drift beyond a threshold pauses the graph for approval before any retrain.
- Fault injection (API outage, late data, database restart) ends in a stated, recoverable state.

## Verification and evidence
| Check | Command | Evidence |
|---|---|---|
| Tests first, then green | `make test` | `results/sprint-03/run/red*.out`, `green.out` |
| Lint | `make check` | `check.out` |
| Mutants | `make mutate` | `mutation.out` |
| Idempotent load | `make run` twice | checksums in `pipeline.out` |
| Parity with DuckDB | `scripts/compare_frozen.py` | `parity.out` |
| Site in a browser | manual, screenshots | `results/sprint-03/site/*.png` |
| Reviews | two independent agents | `results/sprint-03/review.md` |
Frozen sprint-02 evidence (DuckDB): `results/sprint-02/` metrics, tables, `run/mutation.out`
(59 of 62 mutants killed; the 3 survivors are carried as tickets in sprint 03).
