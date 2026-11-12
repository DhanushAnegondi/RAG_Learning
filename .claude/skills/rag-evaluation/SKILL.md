---
name: rag-evaluation
description: "Design eval sets, retrieval and generation metrics, LLM-as-judge rubrics, chaos tests and before/after comparisons for RAG. Use when measuring quality, claiming an improvement or testing fault tolerance."
---

# RAG evaluation

A metric is a claim. It needs an eval set, a run, and recorded provenance (see `verification-gate`).

## Rules

1. Eval rows carry a category, a ground truth, and evidence substrings. See [eval set design](references/eval-design.md).
2. Cover four categories: `exact_term`, `semantic`, `out_of_corpus`, `unanswerable`. Include distractors and exact identifiers.
3. Measure retrieval and generation separately; a wrong answer may be a retrieval miss or a generation fault.
4. The judge model differs from the generator, runs at temperature 0, and scores against a written rubric.
5. Compare systems on the same corpus, the same eval set and the same seed. Record models, commit, corpus hash, eval-set hash.
6. Add a deterministic check next to every judge score where one exists (key-fact match).
7. Chaos evals inject faults at a stated rate with a seed. Offline mode needs no key and is deterministic.
8. Results go to a git-ignored directory; only a curated `RESULTS.md` with provenance is committed.
9. Never write a number you did not measure. Small eval sets (about 40 rows) give wide error bars: say so.

## Resources

- [Eval set design](references/eval-design.md): categories, row schema, evidence labels.
- [Metrics and judging](references/metrics-and-judging.md): hit@k, MRR, recall@k, correctness, faithfulness, abstention, RAGAS.
- [Chaos and comparison](references/chaos-and-comparison.md): fault injection, before/after discipline.
- [Scenario matrix template](assets/templates/scenario-matrix.md)
