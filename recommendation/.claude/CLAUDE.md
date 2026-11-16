# cinebridge harness (recommendation_system)

Python + DuckDB SQL movie recommender on real data: TMDB+IMDb metadata (English + Telugu) and
MovieLens 32M ratings. Start with `docs/agents/project-standards.md` (mandatory: source in repo,
tests first in `tests/` + `CATALOG.md`, ponytail review of code and tests, `results/index.html`
for all sprints, stack-diagram captures) and `ledger/` (latest dated handoff).

## Workflow
- APIV loop (`apiv-method`): Align, Plan, Implement, Verify, Learn. Record the tier before building.
- Tests first: capture RED to `results/<sprint>/run/red*.out`, then GREEN (`make test`), `make check`,
  `make mutate`.
- Independent Sonnet reviewers run `ponytail-review` on code and on tests every sprint;
  findings and fixes go in `results/<sprint>/review.md`.
- `make run`, `make diagram`, `make results`; render and look at the page before reporting.

## Project rules
- Missing data is filled, never dropped. Every filled column has a `<col>_filled` flag and the
  cleaned table has exactly the rows of the staged table. Scope filters (language, vote floor,
  adult) and duplicate ids are not "missing data"; they are counted and shown on the page.
- A placeholder for an unknown person or genre must never count as a similarity signal.
- Telugu titles are kept in Telugu script next to the English title. Files are UTF-8.

## Honesty
- No number on the page or README without a captured run. Ratings on or after the test cutoff
  are never used for fitting, blend-weight selection or popularity counts.
- Say measured, inferred or planned. MovieLens users are not a Telugu audience; say so.

## Skills
`apiv-method`, `verification-gate`, `python-standards`, `sql-standards`, `pipeline-testing`,
`stack-diagram`. Model routing: Sonnet for build/review agents, Haiku for mechanical work.
Commit only when the user asks. Windows console is cp1252: keep printed output ASCII.
