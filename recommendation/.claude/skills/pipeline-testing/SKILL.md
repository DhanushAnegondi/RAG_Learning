---
name: pipeline-testing
description: "Verify data pipeline behavior with unit, contract, integration and recovery tests. Use for transforms, idempotency, late data, schema changes or regression coverage."
---

# Pipeline testing

For fixture isolation and defect-catching expectations, read [scenario design](references/scenario-design.md). Adapt the [scenario matrix](assets/templates/scenario-matrix.md) to the real engine and contracts before writing checks.

Check definitions and thresholds live in `data-quality`; CI wiring in `cicd-data`; pytest mechanics in `python-standards`; SQL style in `sql-standards`. This skill decides which tests exist and how they are built.

## Rules

0. Project code follows [project standards](../../../docs/agents/project-standards.md) section 2: tests in `<project>/tests/`, listed in `tests/CATALOG.md`, RED output captured before implementation, GREEN after, then a ponytail review of the tests.
1. Follow the pyramid: many unit tests (ms, no I/O), fewer integration tests (real engine, seconds), few end-to-end and volume tests (minutes, nightly or pre-release). Count per layer is reviewed in the PR.
2. Every pure transform has a unit test with a tiny inline fixture (3-10 rows, hand-checkable, deterministic: no `now()`, no random without seed, no network). Inject the clock.
3. Every dbt model with non-trivial SQL (CASE, window, regex, dedup, joins with fan-out risk) has a dbt unit test (`unit_tests:` YAML, dbt 1.8+) with `given` inputs and `expect` rows, including edge rows: null, duplicate key, boundary date, empty input.
4. Every model has schema tests (key unique and not null, accepted values, relationships); contract tests assert the published schema equals the ODCS contract (see `data-quality`).
5. Integration tests run on a real engine. Use DuckDB locally and in CI for SQL and Parquet logic; Postgres via testcontainers for OLTP, CDC and merge semantics. Never mock the database or the warehouse client.
6. If the production engine differs from the test engine, tests that depend on dialect behavior (merge, timestamps, collation, decimals) run on the production engine in a CI sandbox. Label gaps `inferred` in the hand-off.
7. Idempotency test is mandatory for every load: run the same interval twice, assert table contents are identical (row set and checksum) and row count unchanged.
8. Backfill test: reprocess a past interval over existing data, assert the result equals a clean build and that neighboring intervals are untouched.
9. Late and out-of-order data tests: deliver events after the watermark, deliver a newer version before an older one, assert the final state equals in-order delivery.
10. Schema evolution test: add a nullable column, add an enum value, widen a type upstream; assert the pipeline passes. Remove a column or narrow a type; assert it fails loudly at the boundary, not silently downstream.
11. Failure-injection tests: source unavailable, source returns partial file, crash after write before commit, duplicate delivery, retry after timeout. Assert no partial publish and a clean re-run converges.
12. Regression by data diff: build the changed models in dev, compare to prod output with symmetric `EXCEPT` (below) or dbt `audit_helper` (`compare_and_classify_relation_rows`, `compare_all_columns`). Every non-empty diff is explained in the PR.
13. Performance test at production-like volume (same row counts and key skew, synthetic if needed) before merging changes to joins, partitioning, or incremental logic. Record runtime and bytes scanned against a stored baseline; fail on more than 25% regression.
14. Parsers and normalizers (dates, IDs, JSON, CSV dialects, units) get property-based tests with `hypothesis`: round-trip, idempotence of normalize, never raises on arbitrary text unless documented.
15. Build fixtures with small builder functions (`make_order(**overrides)`) returning immutable values. Golden files only for formats where the byte layout is the contract (exports, file specs); regenerate them deliberately and review the diff.
16. Test names state behavior: `test_late_event_updates_existing_order_without_duplicating`. No `test_1`, no `test_works`.
17. New code needs 80% line and branch coverage (`pytest --cov --cov-branch`, `--cov-fail-under` on the diff via `diff-cover`). SQL has no coverage tool: every branch of CASE or filter has a row in a unit test.
18. A flaky test is quarantined within 1 day (`@pytest.mark.quarantine`, excluded from the gating job, still run nightly) with a ticket and a 14-day deadline to fix or delete. Never add retries to hide flakiness.
19. A bug fix starts with a failing test that reproduces it.
20. Each test names the break it catches, in the test name or a one-line docstring ("fails if the join key is dropped").
21. Expected rows are derived by hand from the fixture, never by calling the code under test or a copy of its logic (no mirror assertions).
22. Mutation check before done: flip a join key, drop a filter, change a CASE branch; at least one test must fail for each. A mutation that passes means a missing test.
23. The hand-off carries RED and GREEN command output (see `verification-gate`); a test never seen failing is unproven.
24. Wait on a condition (row count reached, partition exists, sensor state) with a timeout and a clear failure message. Never a fixed `sleep`.
25. Review Focus: every transform has a pinned test for each class: nulls, duplicates, late or out-of-order rows, schema drift, empty input. State "not applicable" with a reason in the PR instead of skipping.

## Diff query

```sql
-- both directions; any row returned is a difference. Compare on the full row, or on key + hash for wide tables.
(SELECT 'only_in_dev' AS side, * FROM dev.fct_orders EXCEPT SELECT 'only_in_dev', * FROM prod.fct_orders)
UNION ALL
(SELECT 'only_in_prod', * FROM prod.fct_orders EXCEPT SELECT 'only_in_prod', * FROM dev.fct_orders)
```

Compare over a bounded window (last N partitions) for large tables, and report row count delta and per-column mismatch counts.

## Defaults

| Need | Default | Deviate when |
|---|---|---|
| Python runner | pytest, markers `unit`, `integration`, `slow`, `quarantine` | none |
| Local SQL engine | DuckDB in-process | dialect-specific logic: run on prod engine |
| Service dependencies | testcontainers (Postgres, Kafka, MinIO) | CI forbids Docker: use service containers in CI |
| Dataframe fixtures | pandas/polars built in the test, `assert_frame_equal` with sorted keys | bulk volume tests: generate Parquet |
| Property tests | hypothesis with `max_examples=200` in CI | slow parsers: 50 |
| dbt diff | `audit_helper` in dev against prod clone | warehouse has no clone: bounded window diff |

## Do / Don't

| Do | Don't |
|---|---|
| Assert on row sets, order-independent | Assert on row order without `ORDER BY` |
| Freeze time through a parameter | Call `now()` or `current_date` inside tested logic |
| Seed test data per test, tear down per test | Share mutable tables across tests |
| Test the unhappy path of each check (failing fixture) | Only test that good data passes |
| Mock the HTTP source or clock | Mock the database, warehouse, or object store |

## Checklist (pre-done)

- [ ] Unit tests for every new transform, edge rows included, tests written first
- [ ] Review Focus classes pinned per transform: nulls, duplicates, late rows, schema drift, empty input
- [ ] Expected values hand-derived; each test names the break it catches; mutation check run
- [ ] RED and GREEN output in the hand-off; no fixed sleeps
- [ ] dbt unit tests for new SQL logic; schema and contract tests green
- [ ] Idempotency test: two runs, identical output
- [ ] Backfill, late-data, and out-of-order tests where the pipeline is incremental
- [ ] Schema evolution and failure-injection tests for new sources or loads
- [ ] Data diff vs prod run; every difference explained
- [ ] Volume test run if joins, partitions, or incremental keys changed
- [ ] Coverage at least 80% on new code; no test depends on wall clock, network, or order
- [ ] No new flaky or quarantined test left without ticket and date

## Sources

dbt docs (unit tests, 1.8+); dbt `audit_helper` package; pytest docs; hypothesis docs; testcontainers docs; DuckDB docs; Google SRE Workbook (testing and canarying); Martin Fowler, Test Pyramid.
