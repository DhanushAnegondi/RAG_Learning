---
name: sql-standards
description: "Apply SQL conventions and correctness checks to queries and models. Use when writing, reviewing or tuning SQL, dbt models, MERGE or window logic."
---

# SQL standards

Grain, keys and dimensional design live in `data-modeling`. DDL, indexes and migrations live in `db-development`. This skill is query text and dbt.

## Rules

Style and structure
1. `sqlfluff lint` passes in CI with `dialect` set to the target engine (postgres, snowflake, bigquery, databricks, duckdb). Config lives in `.sqlfluff`; fixes via `sqlfluff fix`.
2. One case style, dbt style: lowercase keywords, functions and identifiers, snake_case names, trailing commas per the dbt sqlfluff config. No quoted identifiers unless the source forces it.
3. Structure is CTEs in three tiers: import (one per source/ref, `select *` allowed only here), logical (one purpose per CTE: filter, dedup, join, aggregate), final (`select` of explicit columns from one CTE). No nested subqueries deeper than one level.
4. Every CTE name says its purpose (`orders_deduped`, `payments_by_order`), never `cte1`, `tmp`, `a`.
5. Column lists are explicit everywhere outside import CTEs. `insert` always names target columns. No `group by 1,2` beyond 3 columns; prefer named columns.
6. Alias every table with a meaningful short name and qualify every column in any query with a join.

Joins and grain
7. Write `inner join` / `left join` explicitly, never bare `join` or comma joins. Join conditions are `on` with equality on keys.
8. Before each join, the key on the side that should be one-row-per-key is proven unique: a dbt `unique` test, a PK, or a preceding dedup/aggregate CTE. State the expected cardinality in a one-line comment when it is not obvious.
9. Never use `distinct` (or `group by` with no aggregate) to remove fan-out. Fix the grain: dedup the source or aggregate before joining.
10. Filters on the right table of a `left join` go in the `on` clause, or the join silently becomes inner.
11. Cross joins are intentional only (date spine, scenarios) and carry a comment. Check row counts before and after each join in tests.

Dedup and NULLs
12. Dedup with `row_number() over (partition by <key> order by <ordering cols>, <unique tiebreaker>) = 1`, or `qualify` where supported (Snowflake, BigQuery, Databricks, DuckDB). The order-by always ends in a column that makes it deterministic (load timestamp, then a unique id).
13. Compare nullable columns with `is distinct from` / `is not distinct from` (or `<=>` / `EQUAL_NULL` where that is the dialect form), not `=` / `<>`.
14. Never `not in (subquery)` when the subquery can return NULL (returns no rows). Use `not exists`.
15. `coalesce` only with a stated intent (a business default). It must not hide a join miss or a bad source; test `not_null` upstream instead.
16. Aggregates ignore NULL: `count(col)` vs `count(*)` is chosen deliberately; `avg` of a nullable column is documented.

Time, numbers, safety
17. Time filters are half-open: `ts >= :start and ts < :end`. Never `between` on timestamps, never `<= end_of_day`.
18. Store and compare in UTC. Convert to a local zone only in the final presentation CTE, with an explicit named zone.
19. Money and rates use `numeric`/`decimal(p,s)`, never float. Integer division is guarded: cast one operand (`x::numeric / y`) and wrap divisors in `nullif(y, 0)`.
20. Predicates are sargable: no function or cast on the indexed/partition/cluster column (`where ts >= :d`, not `where date(ts) = :d`; `where id = :id`, not `where id::text = :id`). Filter on the partition column so pruning happens.
21. Values reach SQL only as bound parameters. No string concatenation or f-strings (identifiers come from an allowlist). See `python-standards` for driver usage.

Writes
22. DDL is idempotent: `create or replace`, `create table if not exists`, `drop ... if exists`. A job rerun produces the same state.
23. `merge` source must be unique on the match key; a source row matching one target row twice raises a cardinality error (Postgres, Databricks, BigQuery, Snowflake by default) or updates nondeterministically (Snowflake if error-on-nondeterministic is off). Dedup the source first, then merge. Include `when matched and <changed cols differ>` to avoid no-op rewrites.
24. Prefer set-based `merge`/`insert ... on conflict` over delete-then-insert unless both run in one transaction.

dbt (1.8+)
25. Reference models with `ref()` and raw tables with `source()` only; no hardcoded schema.table names. Layers: staging (1:1 with source, rename/cast only) -> intermediate -> marts.
26. Public/mart models set `contract: {enforced: true}` with column types, `constraints`, and a `version` when breaking.
27. Every model has `unique` + `not_null` on its grain key, `relationships` on foreign keys, `accepted_values` on enums. Logic-bearing models also get dbt unit tests (`unit_tests:` block, 1.8+) with given/expect rows including NULL and duplicate cases.
28. Incremental models set `unique_key`, wrap the filter in `{% if is_incremental() %}`, and use a lookback window (`where updated_at >= (select max(updated_at) - interval '3 days' from {{ this }})`) for late data. Set `on_schema_change`. The model must also be correct under `--full-refresh`.

Performance
29. Read the plan (`EXPLAIN`, or the warehouse query profile) before and after tuning; record the change in the PR. See `db-development` for Postgres plan reading.
30. Aggregate to the join grain before joining large tables; filter early; select only needed columns.
31. No `order by` in subqueries/CTEs/views unless paired with `limit` or a window; sort once at the end if required.
32. Watch exploding joins: compare `count(*)` of the result with the driving table in a test.

## Defaults

| Decision | Default | Deviate when |
|---|---|---|
| Linter | sqlfluff, dbt templater for dbt projects | Dialect unsupported: pin nearest dialect, note it |
| Dedup | `qualify row_number()` | Engine lacks qualify: wrap in a CTE and filter |
| Materialization | view (staging), table (small marts), incremental (large append/upsert), ephemeral only for tiny reuse | Needs snapshots: `snapshot`; query-time cost matters: table |
| Time type | `timestamptz` / `timestamp_ntz` in UTC | Source gives local time: convert at staging |
| Incremental strategy | `merge` (or `delete+insert` on partition) | Append-only immutable facts: `append` |

## Patterns

```sql
with orders as (select * from {{ ref('stg_orders') }}),

orders_latest as (
    select * from orders
    qualify row_number() over (
        partition by order_id order by updated_at desc, load_id desc
    ) = 1
)

select order_id, customer_id, amount_usd, updated_at
from orders_latest
where updated_at >= :start and updated_at < :end
```

## Checklist

- [ ] `sqlfluff lint` clean for the target dialect; lowercase, explicit columns, CTE tiers, meaningful names.
- [ ] Every join: explicit type, key uniqueness proven, row-count test; no `distinct` as a fix.
- [ ] Dedup has a deterministic tie-breaker; NULL comparisons use `is distinct from`; no `not in` over nullable subqueries.
- [ ] Time ranges half-open UTC; money numeric; divisions guarded; predicates sargable.
- [ ] No concatenated SQL; DDL idempotent; `merge` source deduped.
- [ ] dbt: `ref`/`source` only, contract on public models, grain tests, unit tests for logic, incremental has `unique_key` + lookback and survives full refresh.
- [ ] Plan inspected for any query over a large table.

## Reusable resources

Read [query correctness guidance](references/query-correctness.md) when adapting this skill to a project. Copy the [project worksheet](assets/templates/query-correctness.md) into that project's tracked artifacts and replace its inputs; unrun checks remain unverified. These resources supplement the rules above and the project's actual versions and constraints.

## Sources

dbt Labs style guide and docs (contracts, unit tests 1.8, incremental models); sqlfluff docs; PostgreSQL docs (EXPLAIN, MERGE, NULL handling); Snowflake, BigQuery and Databricks SQL references (QUALIFY, MERGE); Use The Index, Luke; ISO/IEC 9075 (three-valued logic).
