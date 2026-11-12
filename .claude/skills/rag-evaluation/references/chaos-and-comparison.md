# Chaos and comparison

## Fault injection
- Fault kinds: timeout, 429, 500, empty structured output, embeddings down, web search down.
- Seeded random injection at rate `p`, so a run reproduces.
- Offline mode: fake chat and embeddings, no key, deterministic. Measures robustness only, not answer quality.
- Live mode: patch the provider classes at class level so the same harness drives both old and new code.
- Report the error recovery rate (definition in `llm-reliability`), crash rate, degraded rate, and the fault counts actually injected.
- Offline chaos numbers must not be presented as live quality numbers.

## Before/after discipline
1. Same corpus, same eval set, same seed, same judge model for both systems.
2. Run each system in its own process when both import the same package name.
3. Record in the result file: system label, commit or tag, generator/grader/judge/embedding models, corpus hash, eval-set hash, UTC time, command.
4. Compare per category, not just overall. Note categories where the new system is worse.
5. Run twice or note variance when the judge or sampling is non-deterministic.
6. A difference smaller than the noise on about 40 rows is not a finding.
7. If a run fails or is partial, keep it and say so; do not cherry-pick.

## Reporting
`RESULTS.md` holds a curated table plus provenance and limits (set size, synthetic corpus, judge caveats). Raw result JSON stays git-ignored.
