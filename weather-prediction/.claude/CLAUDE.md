# weatherwise harness

Python + DuckDB SQL pipeline on real Open-Meteo data. Start with `docs/agents/project-standards.md`
(mandatory: source in repo, tests first in `tests/` + `CATALOG.md`, ponytail review of code and tests,
`results/index.html` for all sprints, stack-diagram captures) and `ledger/` (latest dated handoff).

## Workflow
- APIV loop (`apiv-method`): Align, Plan, Implement, Verify, Learn. Record the tier before building.
- Tests first: capture RED to `results/<sprint>/run/red*.out`, then GREEN (`make test`), `make check`,
  `make mutate`.
- Independent Sonnet reviewers run `ponytail-review` on code and on tests every sprint;
  findings and fixes go in `results/<sprint>/review.md`.
- `make run`, `make diagram`, `make results`; render and look at the page before reporting.

## Honesty
- No number on the page or README without a captured run. Test window is never used for fitting,
  model selection or band calibration.
- Say measured, inferred or planned. ERA5 is reanalysis, not a station.

## Skills
`apiv-method`, `verification-gate`, `python-standards`, `sql-standards`, `pipeline-testing`,
`stack-diagram`. Model routing: Sonnet for build/review agents, Haiku for mechanical work.
Commit only when the user asks. Windows console is cp1252: keep printed output ASCII.
