# Sprint 01 ponytail review

Two independent reviewers (Sonnet agents, read-only) ran `ponytail-review`: one on code, one on
tests. Both returned VERDICT: FAIL. Every finding below is fixed, deferred with a reason, or
rejected with a reason. Evidence: `run/red-review.out` (new tests failing first), `run/green.out`,
`run/check.out`, `run/mutation.out`.

## Code review (VERDICT: FAIL -> fixed)

Passed as reviewed: error sign, 24-hour local-day aggregation, lead alignment, no test-window
leakage, same-day baselines, idempotent loads, allowlisted SQL identifiers.

| # | Finding | Outcome |
|---|---|---|
| 1 | Outlook caption claimed "8 in 10 days inside"; measured coverage was 62-78% | Fixed: caption now prints measured coverage per series from the eval tables |
| 2 | Finding credited "bias correction" where raw was kept; tmin lead 7 regression (-66.5%) hidden | Fixed: `short_range_finding()` lists leads where raw was kept, where correction helped, and the worst lead; test `test_short_range_findings_report_kept_raw_and_worst_lead` |
| 3 | `--skip-fetch` on a later day silently turned days 1-7 into climatology | Fixed: `assemble_outlook` raises when any lead 1-7 published value is missing; tests for 0 and 2 live days |
| 4 | Anomaly age unchecked; gaps could be skipped | Fixed: `models.recent_anomaly()` raises if the last observation is > 2 days old or the window has a gap |
| 5 | Long-range band measured in-sample (too narrow) | Fixed: `pipeline.calibrate_bands()` fits on all but the final year and measures that year. Coverage is still below 80% for tmax (67-82%): stated on the page, next sprint |
| 6 | Train cut on target date, not issue date (about 0.1% of rows) | Deferred: stated in Known limits |
| 7 | Hard-coded "Sprint 01", "12 months", "4-fold", "2%", stale bias comment | Fixed: interpolated from args and `LeadCorrector` defaults |
| 8 | `{var}` formatted into SQL without a check | Fixed: `assert var in VARIABLES` in both functions |

## Test review (VERDICT: FAIL -> fixed)

| # | Finding | Outcome |
|---|---|---|
| 1 | 502 with HTML body escaped as JSONDecodeError, no retry (real bug) | Fixed in `ingest.fetch_json`; test + mutant |
| 2 | `fetch_all` asked for an inverted date range on 1 January (real bug); untestable session | Fixed: session injectable, empty year skipped; test with today = 2027-01-01 + mutant |
| 3 | Request params (timezone, lead names, forecast_days) unasserted | Fixed: `test_fetchers_send_location_timezone_and_variables` + mutant |
| 4 | SQL grain tested with one city and one lead | Fixed: 2 cities x 2 leads test; mutants for join key and staging grain |
| 5 | Outlook seam (lead 7), varying decay/quantiles, missing live days untested | Fixed: seam test with per-lead coef/quantiles; missing-live tests; mutants |
| 6 | Leakage in `evaluate_short` / `evaluate_long` untested | Fixed: +10 C step inside the test window must not change fits, decay, bands, chosen method |
| 7 | Only `actual_daily` loader tested | Fixed: idempotency + duplicate guard parametrized over all three; issued_on key test; snapshot allowlist test |
| 8 | 429 retry and backoff value untested | Fixed |
| 9 | Short history, band clamp untested | Fixed (clamp test + mutant). GBM sign bug would only show as "never selected": accepted, CV guards selection |
| 10 | Window 3 and quantiles tested only at degenerate settings | Fixed: hand-computed window-3 decay (first version did not kill the partial-window mutant; fixture changed), 10-residual quantiles |
| 11 | stg null filter, rmse, p10/p90 unasserted | Fixed: end-to-end null test, hand-computed rmse/p10/p90, exactly-3 C boundary test |
| 12 | Report: CSV/finding escaping, charts, sprint-9 vs sprint-10 | Fixed: escaping + chart test; natural sort (real bug: text sort) |
| 13 | Vacuous period assert; climatology expectation mirrored `seasonal_features` | Fixed: vacuous assert removed; hand-computed expected value and a hand-values test |
| 14 | RED evidence was stub NotImplementedError; mutation script counted crashes as kills | Fixed: review tests' RED is behavioral (`red-review.out`); mutation script names the killing test, separates CRASHED, timestamps the run, runs the full suite, 29 mutants |
| 15 | CATALOG "Not covered" understated gaps | Fixed: rewritten |
| 16 | sprint-9 vs sprint-10 order | Fixed (see 12) |
| 17 | Neighbouring row untouched after correction | Covered by idempotency + replace test; no separate test |

## Found by me before the reviews returned

- `test_report_orders_sprint_10_above_sprint_9` first passed vacuously: "ten" matched `content=`
  in the page head. Unique markers fixed it.
- A synthetic "unbiased" fixture let linear shrinkage legitimately beat raw; fixture corrected.
- DuckDB silently collapses duplicate keys in one `insert or replace`; `error()` guard added.
