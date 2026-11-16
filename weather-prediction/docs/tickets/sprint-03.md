# Sprint 03 tickets: warehouse port to Postgres

Spec: `docs/spec-postgres-agent.md`. Order is the dependency order. Model tier in brackets.

| # | Ticket | Depends on | Done when |
|---|---|---|---|
| T1 | [Sonnet] Compose service `db` (postgres:18, 127.0.0.1 only, healthcheck, volume), `.env.example`, `config.database_url()`, `make up/down`, psycopg + pool in `pyproject.toml`, sqlfluff dialect `postgres` | - | `make up` reports healthy; a test connects |
| T2 | [Sonnet] `sql/migrations/001..` for schemas raw, staging, marts, app; runner `warehouse.migrate()` with `app.schema_migration`; `make migrate` | T1 | migrate twice = no-op; a broken migration rolls back (test) |
| T3 | [Sonnet] Loaders: `copy` to temp + `on conflict do update` for all 7 tables; backup/restore CSV | T2 | idempotency and duplicate-batch tests pass on Postgres; checksum equal after rerun |
| T4 | [Opus] Staging views and marts in the Postgres dialect (percentile_cont, date arithmetic, no `exclude`, no `quantile_cont`) | T3 | all SQL behavior tests pass unchanged in meaning; hand-computed values still match |
| T5 | [Sonnet] `pipeline` and `site` on the new warehouse (pool, cursor per request, numbered params) | T4 | model, pipeline and site tests pass |
| T6 | [Haiku] Real run for Torrance; `scripts/compare_frozen.py` against `results/sprint-02` | T5 | parity within rounding, or each difference explained |
| T7 | [Sonnet] Browser check of the site (forecast, entry in F, comparison, scoreboard, data) with screenshots | T6 | screenshots in `results/sprint-03/site/` |
| T8 | [Sonnet] Close three surviving mutants from sprint 02: null actuals reaching marts, inside-range upper edge, LSTM best-epoch restore | T4 | each mutant killed by a named test |
| T9 | [Sonnet reviewers] Mutation check, ponytail review of code and of tests, fixes, results page, stack-diagram, README, ledger handoff | T7, T8 | `results/sprint-03/review.md`, `results/index.html` rendered and looked at |

Deviation recorded: T2 built one schema with table-name prefixes (raw_, stg_, mart_, log_,
app_) and `schema_migration`, not separate schemas, so every existing test query stays valid.
The agent's tables get their own schema in sprint 04.

Carried from the frozen sprint 02 (already built on DuckDB, ported by T3-T5): four weather
models, cleaning rules, drift / ens_mean / blend candidates, LSTM and mix long range, adaptive
range, forecast log, observations, verification marts, FastAPI site.
