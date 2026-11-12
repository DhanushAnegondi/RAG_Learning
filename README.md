# RAG_Learning

Two small Python RAG projects that share one NVIDIA NIM key and one repo. `corrective-rag` is a
LangGraph Corrective-RAG pipeline (hybrid retrieval, per-chunk grading, web fallback, cited answers)
with an eval harness that compares it against its original version. `experience-copilot` reuses it
as a library to answer questions about your own experience in your own voice. Both run offline in
tests; live runs need a key.

## Projects

| Project | Pattern | Stack | Status |
|---|---|---|---|
| [`corrective-rag`](corrective-rag/README.md) | Corrective RAG: grade, route, correct once, cite or abstain | LangGraph, NVIDIA NIM (Nemotron Nano 30B, Nemotron 3.5 Bolt, Nemotron 3.5 Embed 1B), Chroma + BM25, DuckDuckGo, FastAPI | v1. Live v0 vs v1 measured: crash 17.5% to 0%, hit@4 86% to 100%, routing 50% to 78% |
| [`experience-copilot`](experience-copilot/README.md) | Persona-grounded answers with deterministic post-checks | `crag` as a library, Streamlit, NVIDIA NIM | v1. Live eval, single run after fixes: coverage accuracy 100%, length compliance 100%, 0 attribution errors (17 q); grounding not measured |

The original code is frozen at git tag `v0-baseline`; the eval harness runs it as the comparison
system.

## How work runs

Changes follow the APIV loop: Align, Plan, Implement, Verify, Learn. `.claude/` holds the harness
for it: `CLAUDE.md` (rules), `skills/` (standards such as `rag-evaluation`, `llm-reliability`,
`stack-diagram`) and `agents/` (builder, reviewer, eval, CI and results roles). Prompt, model,
retrieval, routing and interface changes are High tier and need an independent reviewer plus an
eval run. No metric is published without a recorded run.

## API key

One key file for both projects: `.env` at the repo root (git-ignored).

```powershell
Add-Content .env "NVIDIA_API_KEY=nvapi-..."
```

Get a key at https://build.nvidia.com. Never commit or print it. Tests run with the key unset.

## Layout

```
.claude/              harness: CLAUDE.md, skills/, agents/
.github/workflows/    ci.yml
corrective-rag/       src/crag, tests, eval/, data/corpus, docs/
experience-copilot/   src/copilot, app.py, tests, eval/, examples/
```

## CI

`.github/workflows/ci.yml`, on push and pull request touching either project:

- `corrective-rag`: ruff, offline pytest (key unset), an offline chaos smoke run of v1, and a gate
  that fails if the crash rate is above zero or the error recovery rate is below 1.0.
- `experience-copilot`: ruff and offline pytest.
- `eval-live`: manual (`workflow_dispatch`) only; runs the live quality suite with the
  `NVIDIA_API_KEY` repository secret and uploads the result JSON as an artifact.
