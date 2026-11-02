# Experience Copilot V2 plan

Started 2026-11-01. Development branch: `codex/experience-copilot-v2`.
V1 reference: `baseline/experience-copilot-v1` at `f2b924c0297e6a9083ba8523c7d892951bc99bf5`.

## Goal

Improve correct-story retrieval and grounded personal answers while keeping the original available.
Measure retrieval and abstention before claiming a quality improvement. Never promote practice or
constructed experience into confirmed employment history automatically.

## First development pass

- Preserve V1 code path and index. Add explicit V1/V2 choices in CLI and UI.
- Add a source evidence manifest: status, employer, project, ownership, version and optional story ID.
  Unlisted documents are unverified. V2 retrieves confirmed documents only.
- Split on Markdown headings before recursive chunking. Attach bounded parent sections to matches.
- Combine BM25 keyword search with dense vector search using reciprocal rank fusion (RRF).
- Rerank up to 24 candidates and check evidence sufficiency in one structured model call.
  Restrict candidates by employer when explicitly selected or one employer is literally named.
- Return a focused clarification on insufficient evidence. Model/check failures never become coverage.
- Generate cited answers, validate source IDs, then model-check factual claims before displaying them.
- Add 48 fictional evaluation questions, held-out paraphrases, negative cases and a live comparison runner.
- Test source filtering, persistence, idempotent rebuilds, revoked evidence, attribution scope, failure
  handling, citation rejection and V1 compatibility. Obtain a separate code review before committing.

## Acceptance checks

1. Existing V1 tests pass; V1 index remains separate and is never rebuilt by V2.
2. Draft/synthetic/unverified documents cannot enter V2 retrieval or generated answers.
3. Failed evidence checking blocks generation. Failed claim checking blocks draft display.
4. Repeating a V2 ingest does not duplicate IDs. Replacing a source or changing its status switches
   the active snapshot; old collections do not participate in retrieval.
5. Evaluation uses the same fictional corpus for both versions, isolated indexes and explicit model
   settings; errors are failures, never successful abstentions.
6. No private corpus, persona, keys, vector indexes or private evaluation outputs reach GitHub.

## Next iterations, after the first benchmark

| Step | Deliverable | Evidence needed before proceeding |
|---|---|---|
| Review personal sources | Local manifest + reviewed source versions | User confirmation of experience, metrics and ownership; no automatic approval |
| Evaluate real questions | Locally held-out interview set | Human expected stories/claims and acceptable abstentions |
| Tune retrieval | Candidate count, context budget, optional dedicated reranker | Compare fixed dev set, then run unchanged holdout; measure latency as well as retrieval |
| Improve corrections | Change detection and stale-source reporting | A reviewed source correction removes old answers from active retrieval |
| Add follow-ups | Resolve “that project” using selected story IDs | Multi-turn attribution and ambiguity tests |
| Add richer evaluation | Claim-level human scoring and optional Ragas | Unsupported-claim, ownership and employer errors measured separately |

## Design limits

The manifest initially labels whole files, not individual claims. Split mixed fact/practice files
before confirming them. A model-based check reduces risk but is not proof that a claim is true.
Heading parents larger than 4,000 characters fall back to the matched chunk. The local BM25 scan
is appropriate for this small personal corpus; evaluate a search service if the corpus grows large.
Old V2 snapshot collections are retained for recovery and require eventual manual cleanup.
V2 intentionally has no web fallback; company research remains in V1 until separate question routing
and source types are implemented. GraphRAG and general-purpose agents are later options only if
the evaluated questions require them.
