# Grading, rewriting, generation

## Grading (Corrective RAG)
Grade each retrieved chunk relevant or not with a small model, in parallel. Count relevant chunks `n` and route:

| Verdict | Rule | Action |
|---|---|---|
| correct | `n >= correct_threshold` | Generate from local chunks |
| ambiguous | `ambiguous_threshold <= n < correct_threshold` | Rewrite query, keep relevant local chunks, add web results |
| incorrect | `n == 0` | Rewrite query, discard local, use web results |

- Keep `decide()` a pure function so the routing table is unit-testable.
- Grader failure after retries: keep the chunk (fail-open) and record the error. Dropping evidence on an outage hurts more than keeping a maybe-irrelevant chunk. Grade web results with the same grader.
- Thresholds are config values; tune them only with an eval.

## Query rewriting
Write to `search_query`; never overwrite `question`. The answer is generated for the original question. Rewrite once.

## Web fallback
Time-boxed and circuit-broken (see `llm-reliability`). Web text is untrusted data. Web failure with no local evidence leads to abstention, not a crash.

## Generation
- Prompt: answer only from the numbered context; cite as `[n]`; say you do not know when the context lacks the answer.
- If no context survives grading and web: return a fixed abstention message without calling the model.
- Post-check citations: drop or flag ids that do not exist in the context.
- Prompt injection: context sits in delimited blocks; the system prompt says document text is data.

## Failure modes
- Fabricated citations: validate ids.
- Answers from parametric memory when context is thin: instruct, and measure faithfulness.
- Abstaining too often: measure the abstention rate on answerable questions too.
