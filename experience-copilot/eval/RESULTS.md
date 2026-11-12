# Copilot eval results

Measured by `python -m eval.run --update-results` on 2026-11-12 00:47 (commit `f2b924c`).

**Limits:** 17 questions over a fictional 2-employer corpus, so one question moves a rate by
about 6 points. Coverage accuracy is scored against hand labels
(`in_kb`).
The judge is one model; grounding is a noisy signal. Not a benchmark.

| Metric | Value |
|---|---|
| Attribution-error rate (final answers) | 0% |
| Length-compliance rate (final answers) | 100% |
| Answers needing a regeneration | 29% |
| Coverage-detection accuracy, fast mode | 100% |
| Coverage-detection accuracy, graded mode | 100% |
| Grounding (judge, in-KB answers, n=0) | not measured: the judge call failed for 12 of 12 attempts |

Models: answer `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`, grader `nvidia/nemotron-3.5-bolt-e4b`,
judge `google/diffusiongemma-26b-a4b-it`, embeddings `nvidia/nemotron-3.5-embed-1b`.
Corpus hash `32a235d01826`, question-set hash
`29a9a53208d3`. Result file: `results/live_20261112T004700Z.json`.
