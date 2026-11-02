# Fictional retrieval comparison, 2026-11-01

NVIDIA hosted `nvidia/nemotron-3.5-embed-1b`, same model for both versions. Each used a fresh,
isolated index of the same fictional corpus. V1 used its existing top-four dense search; V2 used
the first four hybrid candidates before model reranking. V2 excludes unreviewed, draft and
synthetic distractors; V1 includes them. Thirty answerable questions, including 12 holdouts.

| Measure | V1 | V2 candidates |
|---|---:|---:|
| Expected source in top four | 30/30 | 30/30 |
| Mean reciprocal rank | 0.961 | 0.878 |
| Holdout expected source in top four | 12/12 | 12/12 |
| Holdout mean reciprocal rank | 0.958 | 0.861 |

The fixture is small and expected sources are labeled at file level, not claim level. This is not
a benchmark of personal documents or answer quality, and the lower V2 candidate rank does not
measure V2's final reranked result. The hosted chat endpoints attempted during this run were
unavailable, so answer generation, abstention and end-to-end comparison remain unmeasured.
