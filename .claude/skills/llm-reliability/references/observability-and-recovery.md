# Observability and recovery

## Per-request context
Carry a `RunContext` via `contextvars`: `trace_id`, spans per node (name, latency), `llm_calls`, `retries`, `fallbacks`, `errors`, `degraded`. Tests create a fresh context; no global state.

## Traces
- One JSONL line per request in a git-ignored directory. Fields: trace id, timestamps, route, spans, call records, errors.
- Structured JSON logs carry the trace id. Log counts, ids and durations, never keys or full documents.

## Signals worth tracking
| Signal | Why |
|---|---|
| p50/p95 latency per node | Find the slow stage |
| LLM calls per question | Cost and retry storms |
| Retry and fallback rate | Provider health |
| Degraded rate, abstain rate | Quality drift and outages |
| Crash rate | Must be zero for public entry points |

## Error recovery rate (definition)
Under fault injection: questions that hit at least one injected fault, finish without crashing, and return a usable answer or an explicit abstention, divided by all questions that hit at least one injected fault. Report the injected rate and fault kinds with the number. "Usable" means a non-empty answer or the fixed abstention; an empty or error-text response does not count.

## Readiness
Liveness (process up) is separate from readiness (index present, key configured). Do not mix them.

## Recovery
- Provider outage: pipeline degrades; operators see `degraded` rate rise. No manual action needed unless it persists.
- Corrupt index: rebuild with the ingest command; incremental manifests are safe to delete.
- Use the [recovery runbook](../assets/templates/recovery-runbook.md) for each recurring failure.
