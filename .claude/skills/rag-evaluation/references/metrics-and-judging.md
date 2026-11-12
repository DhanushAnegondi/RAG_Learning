# Metrics and judging

## Retrieval (needs evidence labels, no LLM)
| Metric | Definition |
|---|---|
| hit@k | Fraction of rows whose evidence appears in the top-k retrieved chunks |
| MRR | Mean of 1 / rank of the first chunk containing the evidence (0 if none) |
| recall@k | Fraction of a row's evidence substrings found in the top-k (multi-evidence rows) |

Score only rows that have evidence. Report k.

## Generation
| Metric | How |
|---|---|
| Correctness | Judge compares answer to ground truth with a rubric; plus deterministic key-fact match for short truths |
| Faithfulness | Judge checks each claim in the answer is supported by the retrieved context |
| Abstention accuracy | On unanswerable rows: did it abstain? Also report wrongly-abstained answerable rows |
| Routing accuracy | Actual route equals `expected_route` |
| Crash rate | Runs that raised or returned nothing |
| Latency p50/p95, LLM calls per question | From run records |

## LLM-as-judge rules
1. Judge model differs from the generator (avoids self-preference).
2. Temperature 0; structured output with a score and a one-line reason.
3. Rubric is written down: what counts as correct, partially correct, wrong, and refusal.
4. Judge sees the question, ground truth and answer (and context for faithfulness), nothing about which system produced it.
5. Spot-check a sample of judge verdicts by hand and record agreement.
6. Judge failures are counted and reported, not dropped silently.

## RAGAS, plainly
RAGAS is a library that computes RAG metrics using an LLM as judge. Faithfulness: share of answer claims supported by the context. Context precision: whether relevant chunks are ranked above irrelevant ones. Answer relevancy: whether the answer addresses the question. Context recall: whether the retrieved context covers the ground truth. It adds a dependency and extra judge calls; treat it as an optional cross-check next to your own rubric, never a requirement.
