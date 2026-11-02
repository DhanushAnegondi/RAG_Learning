# Live fictional coverage comparison, 2026-11-01

48 questions: 30 answerable and 18 unsupported. Both versions use NVIDIA's
`nvidia/nemotron-3.5-embed-1b` in isolated fixture indexes. V2 uses
`nvidia/nemotron-3.5-bolt-e4b` for evidence ranking and sufficiency. V1 is original fast mode:
its coverage decision is simply whether retrieval returned any chunks.

| Metric | V1 fast | V2 evidence check |
|---|---:|---:|
| Questions with API errors | 0/48 | 0/48 |
| Correct coverage decisions | 30/48 | 38/48 |
| Correctly covered answerable questions | 30/30 | 20/30 |
| Correctly rejected unsupported questions | 0/18 | 18/18 |
| Expected source among selected passages, answerable questions | 30/30 | 29/30 |
| Mean reciprocal rank, answerable questions | 0.961 | 0.967 |

On a separate eight-question smoke test with answer generation enabled, V2 generated and
model-checked two answers, withheld two answerable cases, and withheld all four unsupported cases.
No independent human claim-level scoring was performed. The 48-question run tests evidence
selection and coverage, not generated-answer quality. Results are fictional, model-dependent,
and one run; they do not demonstrate performance on the user's personal documents.
The V1 and V2 paths perform different work, and V2 filters unreviewed fixture documents.
The evidence checker was excessively cautious on ten supported questions; improve with a
separate dev set and re-evaluate against held-out examples before claiming a quality gain.
