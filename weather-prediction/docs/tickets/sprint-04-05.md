# Sprint 04 and 05 tickets (outline; detailed when sprint 03 closes)

Spec: `docs/spec-postgres-agent.md`.

## Sprint 04: LangGraph planning agent
| # | Ticket | Depends on |
|---|---|---|
| A1 | Reader role `weatherwise_reader` and `sql/agent/*.sql` tool queries (numbered params) | sprint 03 |
| A2 | Typed tools with pydantic schemas; timeout, retry, `agent.tool_call` log with unique `call_id` | A1 |
| A3 | `StateGraph`: route, model, tools, answer; Postgres checkpointer per thread | A2 |
| A4 | Long-term memory (Postgres store): locations, thresholds, units; recalled across threads | A3 |
| A5 | Offline tests with a scripted fake model; kill-and-resume proof script and captured output | A3 |
| A6 | Site chat tab over the agent; grounding rule: no number outside a tool result | A4 |
| A7 | Mutation check, two reviews, results page, diagram, README | A5, A6 |

## Sprint 05: operations
| # | Ticket | Depends on |
|---|---|---|
| O1 | Daily run entry point (fetch, load, forecast, log) with a run table | sprint 04 |
| O2 | Drift detection on recent forecast error; graph interrupt for approval before retraining | O1 |
| O3 | Scored question set graded against the database | sprint 04 |
| O4 | Fault injection: API outage, late data, database restart; each ends in a stated state | O1 |
| O5 | Mutation check, two reviews, results page, diagram, README | O2, O3, O4 |
