# Query correctness before tuning

Checked: 2026-11-09. SQL behavior varies by engine/version; the links describe PostgreSQL 18, not every warehouse dialect.

Declare driving grain and join cardinality before adding joins. A many-to-many join can multiply valid measures even if final rows look plausible. Independently compute expected totals on a small fixture and check unmatched rows.

A deterministic row choice needs a complete ordering rule. Equal timestamps require a stable tie-breaker. Window aggregates also have frame semantics: an ORDER BY can make an aggregate cumulative; specify the intended frame for whole-partition or running calculations. PostgreSQL's default frame can make last_value surprising.

Test nulls, duplicate inputs, ties, empty input and an exact interval boundary. Compare outputs as multisets when duplicates matter; a set difference can hide multiplicity defects. Prefer grouped row counts or equivalent engine-supported comparison over assuming EXCEPT semantics.

Read execution plans after correctness checks. EXPLAIN estimates and actual execution answer different questions; EXPLAIN ANALYZE executes writes. Use a controlled environment for side-effecting plans.

Adaptation: name engine, version, timezone, decimal scale, NULL policy and comparison semantics. Dialect conveniences such as QUALIFY must be verified rather than copied into unsupported engines.

## Sources
- [PostgreSQL 18 SELECT and set operations](https://www.postgresql.org/docs/18/sql-select.html)
- [PostgreSQL 18 window functions](https://www.postgresql.org/docs/18/functions-window.html)
- [PostgreSQL 18 EXPLAIN](https://www.postgresql.org/docs/18/using-explain.html)
