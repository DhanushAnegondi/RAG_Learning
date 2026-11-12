# Scenario matrix: <component or suite>
Tier and reason: <route>
Project / revision / environment: <commit, python, offline or live>

| Scenario | Category / fault | Input fixture | Expected behavior | Check (command or metric) | Result |
|---|---|---|---|---|---|
| Exact identifier lookup | exact_term | <row id> | Evidence in top-k; hybrid beats dense | <hit@k> | unrun |
| Paraphrased question | semantic | <row id> | Local route, cited answer | <correctness> | unrun |
| Needs web | out_of_corpus | <row id> | Route web, cited source | <routing acc> | unrun |
| Undocumented policy | unanswerable | <row id> | Abstains | <abstention acc> | unrun |
| LLM timeout | fault | rate <p>, seed <s> | Retry, fallback, answer returned | <recovery rate> | unrun |
| Embeddings down | fault | | BM25-only, degraded=true | <test name> | unrun |
| Web down | fault | | No crash; local answer or abstain | <test name> | unrun |
| Bad structured output | fault | | One retry then fallback | <test name> | unrun |

Provenance for measured rows: <result file path, models, corpus hash, eval-set hash>
Gaps: <unrun scenarios and why>
