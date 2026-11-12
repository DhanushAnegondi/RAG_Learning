# Error handling and degradation

## Taxonomy
| Class | Examples | Action |
|---|---|---|
| Transient | Timeout, connection reset, HTTP 429, 5xx | Retry with backoff + jitter, then fallback model |
| Permanent | 400 bad request, 401/403 auth, 404 unknown model | No retry. Fail the call fast; surface a clear error. Fallback model only for 404 unknown model |
| Parse | Empty output, invalid JSON, schema mismatch | One plain-text retry, then parse fallback (e.g. keyword heuristic) |

Map provider exceptions into these three types in one `classify(exc)` function. Unknown exceptions default to permanent so bugs are not hidden by retries.

## Retries
- Attempts: small (3). Backoff: base 0.5s, exponential, full jitter, cap around 8s. Honor `Retry-After` on 429 if present.
- Retry only idempotent calls (LLM completions and embeddings are).
- Total time budget per request: attempts times timeout must fit the caller's deadline.

## Timeouts
Set per call (chat 30s, web 10s are starting points). A timeout is transient.

## Model fallback chain
Primary, then secondary, then smallest. Record which model answered. Fallback quality is lower; note it in the result so evals can see it.

## Circuit breaker
Closed: calls pass. After N consecutive failures: open, skip calls for a cooldown and return the degraded result immediately. After cooldown: allow one probe; success closes. Keep state in an object owned by the client or graph, not a module global.

## Fail-open vs fail-closed (decide per node)
| Node | Default | Reason |
|---|---|---|
| Chunk grader | Fail-open: keep the chunk | Dropping evidence on an outage is worse than a noisy chunk |
| Query rewriter | Fail-open: use the original question | Rewrite is an optimization |
| Web search | Fail-open: empty results, error recorded | Local evidence may still answer |
| Dense retrieval | Degrade: BM25 only | Keyword search still works |
| Generator | Fail-closed: abstain or return a clear degraded message | Never invent an answer without a model |
| Input validation | Fail-closed: reject | Bad input is the caller's error |

Record every swallowed fault in `errors`; swallowing silently is a bug.

## Graceful degradation checklist
- Each dependency has a named fallback or an explicit abstain.
- `degraded` is true whenever a fallback served the request.
- The response says what was skipped.
