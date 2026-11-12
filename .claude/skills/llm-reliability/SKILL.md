---
name: llm-reliability
description: "Make LLM and retrieval pipelines survive faults: error taxonomy, retries, timeouts, fallbacks, circuit breakers, fail-open or fail-closed choices, observability and recovery. Use when writing or reviewing LLM client, graph-node or web-call code."
---

# LLM reliability

Applies to every call that leaves the process: chat model, embeddings, web search. Faults are expected; the pipeline reports them instead of crashing.

## Rules

1. All provider calls go through one client class. No node calls the SDK directly. The provider factory is the test seam.
2. Classify every error: transient, permanent or parse (see [error handling](references/error-handling.md)). Retry only transient.
3. Every call has an explicit timeout. No unbounded waits.
4. Retries use exponential backoff with jitter, a capped attempt count, and `reraise`.
5. After retries are exhausted, walk a model fallback chain (larger model, then smaller), then degrade.
6. Parse errors get one plain-text retry, then a defined parse fallback. Never loop on bad output.
7. Each node declares fail-open or fail-closed (table in the reference) and a test proves it.
8. Public entry points never raise on runtime faults. They return a result with `degraded`, `errors` and a usable answer-or-abstain. Raise only on invalid input.
9. Optional dependencies (web search) sit behind a circuit breaker with a cooldown.
10. Every request gets a trace id; every LLM call is recorded (model, purpose, latency, retries, fallback, error). Never log secrets, keys or full prompts.
11. Test with injected faults, offline and deterministic (see `rag-evaluation` chaos evals).

## Resources

- [Error handling and degradation](references/error-handling.md): taxonomy, retry settings, fallbacks, breakers, fail-open table.
- [Observability and recovery](references/observability-and-recovery.md): traces, metrics, error recovery rate.
- [Recovery runbook template](assets/templates/recovery-runbook.md)
