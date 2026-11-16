# Sprint 05 tickets: operations (tier High)

Spec: `docs/spec-postgres-agent.md`. Decisions made at the start of the sprint:

- A daily run does not re-choose methods. It refits the methods chosen at the last accepted
  selection (`app_model_eval.chosen`) on the newest data and issues today's forecast.
- Re-choosing methods ("retraining") happens only when drift is found AND a person approves,
  or when no selection exists yet (first run).
- Drift = this project's average miss over the last 30 scored days, per variable and lead 1-7,
  against the held-out average miss stored at selection time. Flagged when there are at least
  14 scored days, the recent miss is over 1.5 times the stored one and over 0.5 C worse.
- The run is a LangGraph graph with a Postgres checkpoint per step and an interrupt at the
  approval gate. Every run has a row in `app_run_log` with its state.
- Data lag: the models need an observation at most 2 days old (`models.MAX_OBS_AGE_DAYS`).
  Actuals one day behind give a warning on the run; two or more stop it before any forecast
  is issued. (First written as 3 and 7 days; the models' own limit made that wrong.)

| # | Ticket | Depends on |
|---|---|---|
| O1 | `sql/migrations/003_ops.sql` (`app_run_log`), `sql/ops/*.sql`, `ops.py`: daily run, run log, pinned forecast (`build_outlook(pin=...)`, `LeadCorrector.fit(pin=...)`) | sprint 04 |
| O2 | Drift query and gate: graph interrupt, `run_daily.py --approve / --decline` | O1 |
| O3 | Scored question set (`evals/questions.json`, graded against the database, live model) | sprint 04 |
| O4 | Fault injection script: API outage, late data, database restart; each ends in a stated state | O1 |
| O5 | Carried over: trim long conversation history; pool checks connections after a database restart; Compose restart policy | sprint 04 |
| O6 | Mutation check, two reviews, results page, diagram, README | O2, O3, O4 |

Acceptance (from the spec):
- Drift beyond the threshold pauses the graph for approval before any retrain.
- Fault injection (API outage, late data, database restart) ends in a stated, recoverable state.
- The assistant's answers are scored against the database on a fixed question set.
