# Sprint 03 ponytail review

Two independent reviewers (Sonnet agents, read-only) applied `ponytail-review`: one to the code,
one to the tests. Both returned VERDICT: FAIL. Every finding is fixed, deferred with a reason, or
accepted with a reason. Evidence: `run/red-review.out` (new tests, first run), `run/green.out`,
`run/check.out`, `run/mutation.out`, `run/parity.out`.

## Code review (VERDICT: FAIL)

Passed as reviewed: causality of the recent-bias feature and the adaptive range, Postgres
dialect (percentile, rounding, date arithmetic, nulls), load transaction and duplicate handling,
SQL identifier allowlist, migration rollback, live-over-hindcast ranking, pooled connections
returned on every path, unit conversion and escaping in `web/app.js`, no password in any output.

| # | Kind | Finding | Outcome |
|---|---|---|---|
| 1 | BUG | A second run on the same day rewrote that day's live forecasts, while README and comments said "never rewritten" | Fixed: `load_forecast_log.sql` updates only hindcast rows; the first live forecast of an issue day is kept. Test `test_a_live_forecast_is_written_once...` + mutant |
| 2 | BUG | README printed `{TESTS}` / `{MUTANTS}`, linked a diagram, review and mutation output that did not exist yet | Fixed: numbers filled from `green.out` and `mutation.out`; diagram, this file and the mutation run produced |
| 3 | BUG | README said the range held "67 to 73%" for days 8-30 (CSV: 66.5 to 74.3) and "4 weather models, 2022 on" (two start in early 2024) | Fixed: 67 to 74%; README states which models start when |
| 4 | RISK | Long-range replays were filed as issued on the last observed day; a forecast is issued the day after | Fixed: replay rows are logged one lead shorter (issued = origin + 1), matching live. The long-range evaluation table still counts from the last observed day; its caption says so. Mutant added |
| 5 | RISK | Makefile and `--sprint` defaulted to sprint-02, so a plain `make run` would overwrite the frozen baseline | Fixed: default is sprint-03 |
| 6 | RISK | `capture_site.py` could leave its example reading in the real scoreboard if it failed | Fixed: delete in `finally` |
| 7 | NIT | Results-page pattern still said DuckDB | Fixed |
| 8 | RISK | `band_p10_p90_c` was the starting range while coverage is measured with the adaptive range | Fixed: renamed `start_band_c`, caption explains. Leaderboard `test_days` counts all test rows, the eval table drops rows without a persistence baseline: accepted, both are labelled |
| 9 | RISK | Two quick clicks could start two refreshes; a NUL in a note gave a 500 | Fixed: lock around the refresh state; note refused with a reason (test + mutant). Accepted: a refresh holds one of 4 pooled connections and briefly blocks readers while models rebuild (single-user site); a failed CSV backup after a saved entry returns 500 |
| 10 | RISK | Two processes migrating an empty database could collide; `connect` leaked on a failed migration | Fixed: advisory lock around `migrate`; connection closed on failure |
| 11 | NIT | `run_city` ran the whole old long-range evaluation only to get a climatology | Fixed: fits the climatology directly |
| 12 | NIT | `assert` guarded SQL built with the variable name | Fixed: explicit `ValueError` |
| 13 | NIT | Checksum dropped nulls (`concat_ws`) and skipped precipitation in the live table | Fixed: `row(...)::text` |
| 14 | NIT | `compare_frozen.py` flooded `parity.out` with warnings | Fixed |
| 15 | NIT | Unescaped date in a data attribute; no error handling in one click handler; date default could shift a day in far-east time zones | Fixed |
| 16 | NIT | Training cut on target date, not issue date | Kept as a stated limit |
| 17 | NIT | Ticket T2 promised separate schemas; the build uses one schema with prefixes | Recorded in the ticket and the spec |

## Test review (VERDICT: FAIL)

Passed as reviewed: all 66 mutant patterns present in the source at review time, both causality
tests pin the exact one-day shift in both directions, expectations are hand-derived, no test
depends on the clock, the network or test order, catalog lists every test.

| # | Kind | Finding | Outcome |
|---|---|---|---|
| 1 | STALE-MUTANT | No mutation run existed for the Postgres code; catalog claimed the DuckDB run covered it | Fixed: `make mutate` run on Postgres with 79 mutants (`run/mutation.out`); catalog corrected |
| 2 | WEAK-TEST | The bad-batch test failed at COPY, before any write, so it could not prove a load is atomic | Fixed: `test_a_load_that_fails_halfway_undoes_its_own_delete` fails the insert after the delete; mutant removes the transaction |
| 3 | WEAK-TEST | The failed-migration test would pass without the transaction wrapper (Postgres wraps a multi-statement string itself); file order untested | Partly fixed: order and stop-at-first-failure are tested, with a mutant for the order. The wrapper only protects "file applied but not recorded"; no test forces that, stated in the catalog |
| 4 | WEAK-TEST | The reset guard was tested only as a function, not that `reset` calls it | Fixed: `reset` on a fake connection named `weatherwise` must send no SQL; mutant |
| 5 | UNTESTED | `run_city` end to end, the LSTM and mix path | Fixed: offline `run_city` test on a small synthetic city (live rows, replay issue days, no replay before the test window, bias removed, leaderboard replaced not doubled); `long_backtests` test with the LSTM. `refresh`, `build_outlook` with the LSTM chosen: still only in the real run, stated |
| 6 | UNTESTED | history, leaderboard, error-by-lead, quality, issues, check endpoints; `records()` shortened a 00:00:30 timestamp to a date | Fixed: endpoint tests with hand-set rows and a 404 per endpoint; `records()` bug fixed (test was red first, see `red-review.out`) |
| 7 | UNTESTED | Pooled connection returned on error | Fixed: 12 refused requests against a pool of 4, then a normal one; mutant |
| 8 | UNTESTED | Checksum of the forecast tables; corrected forecast hour replaced | Fixed: test + mutant; `loaded_at` moves only on a real change (test + mutant) |
| 9 | UNTESTED | Unit conversion in `web/app.js` | Not automated: checked by hand in the browser (77 F entry stored as 25 C is tested at the API). Stated in the catalog |
| 10 | MISSING-MUTANT | Window size, the other shift direction, margin boundary, live rewrite, checksum, migration order, reset guard, mix | Added (13 mutants) |
| 11 | CATALOG | False mutation claim; RED described as "whole suite" (it was 12 connection errors); stale `date.today()` line; wrong layer label | Fixed |
| 12 | NIT | Unclosed test connections; "new database" in two test names is the same database emptied | Accepted: connections close at process exit; names kept, docstrings say what is done |

## Found by me before the reviews returned

- After the port, a batch with a repeated key no longer failed: the "only update changed rows"
  clause skipped the update, so Postgres never raised. An existing sprint-01 test caught it. The
  staging table now carries the primary key.
- The parity script reported `nan -> nan` as a difference (pandas 3 keeps NaN through
  `astype(str)`).
- The live forecast changed between the DuckDB and Postgres fetches (new upstream run), which
  explains the only parity difference; verified from both stored tables.

## Mutation run (after both reviews)

First run on Postgres: 74 of 79 killed. The five survivors and what was done:

| Mutant | Why it survived | Fix |
|---|---|---|
| three primary-key changes in `sql/migrations/001_tables.sql` | the test database was already migrated, so the changed file never ran | `scripts/mutation_check.py` drops the test schema before and after a migration mutant |
| impossible min accepted | no test had a low below -60 C with the high still above it | row added to `test_cleaning_rejects_impossible_actuals_and_lists_the_reason` |
| long replay filed a day early | the issue-day assertion compared values computed from the same columns | `test_run_city_...` now asserts the replayed leads are exactly 1..9 |

Rerun: 79 of 79 killed (`run/mutation.out`). Limits of that evidence: the three key mutants are
killed by the first test that loads data (the loader's `on conflict` target no longer exists), and
one of them by a test error rather than a failed assertion (no test name is printed), so they prove
the key is required, not that a dedicated test describes it.
