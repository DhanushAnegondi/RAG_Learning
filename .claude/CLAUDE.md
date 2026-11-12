# RAG_Learning harness

Two Python RAG projects: `corrective-rag` (LangGraph Corrective-RAG on NVIDIA NIM, Chroma + BM25 hybrid, DuckDuckGo fallback) and `experience-copilot` (persona answers grounded in personal docs). Keep the repo clean and small.

## Workflow
- APIV is the loop: Align, Plan, Implement, Verify, Learn. Skill: `apiv-method`.
- Record `Tier: Low|Standard|High - reason` before implementing. Prompt, model, retrieval, routing or interface changes are High: separate builder and reviewer, offline suite plus eval run.
- Self-review never closes High work. Missing reviewer or tool leaves the gate open.

## Model routing
- Opus lead: orchestrates, decides, final review.
- Sonnet agents: build, test, review.
- Haiku: mechanical work (file lookups, formatting).
- Set `model` explicitly when spawning.

## Roster (`agents/`)
| Agent | Use for |
|---|---|
| `ai-architect` | HLD/ADR, pattern choice |
| `rag-engineer` | Retrieval, graph, LLM client code |
| `eval-engineer` | Eval sets, metrics, chaos runs |
| `ai-reviewer` | Independent PASS/FAIL review, read-only |
| `cicd-engineer` | GitHub Actions: offline tests, manual eval job |
| `results-capturer` | Diagrams and RESULTS tables |

## Standards (`skills/`)
`rag-design-patterns`, `llm-reliability`, `rag-evaluation`, `python-standards`, `verification-gate`, `apiv-method`, `stack-diagram`.

## Honesty on metrics
- No number in any README or RESULTS.md without a recorded eval run (same corpus and eval set, models, commit, corpus hash).
- Offline chaos numbers measure robustness only, not answer quality.
- Say planned, executed, inferred or measured; never blur them.

## Repo hygiene
- Tests run offline with `NVIDIA_API_KEY` unset.
- Nothing committed: logs, caches, venvs, chroma stores, traces, result JSON. Only curated `eval/RESULTS.md`.
- The API key lives in the root `.env` only. Never print, log, copy or hard-code it.
- Do not commit or push unless the user asks.
- Windows + PowerShell primary; read and write text as UTF-8.
