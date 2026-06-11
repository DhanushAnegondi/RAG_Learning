# Corrective RAG (CRAG)

A self-correcting retrieval pipeline built as a **LangGraph state machine**. It grades each
retrieved chunk for relevance; if the corpus can't answer, it rewrites the query and falls back to
web search before generating. The point: *don't blindly trust what you retrieve.*

```
question -> retrieve -> grade -> decide() --[enough relevant]--> generate -> END
                                      \--[too few]--> transform_query -> web_search -> generate -> END
```

Stack (NVIDIA NIM): `ChatNVIDIA meta/llama-3.3-70b-instruct` · `NVIDIAEmbeddings nv-embedqa-e5-v5` ·
Chroma · `duckduckgo-search`. One key: `NVIDIA_API_KEY`.

## Quickstart (Windows / PowerShell)

```powershell
# 1. install
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .

# 2. key  (get one at https://build.nvidia.com — starts with nvapi-)
Copy-Item .env.example .env
# edit .env and paste NVIDIA_API_KEY

# 3. M0 smoke test
$env:PYTHONPATH = "src"; .\.venv\Scripts\python.exe scripts\smoke_test.py

# 4. ingest your docs (drop files into data/corpus/ first; samples are provided)
.\.venv\Scripts\python.exe -m crag.cli ingest

# 5. ask — watch the route it takes
.\.venv\Scripts\python.exe -m crag.cli ask "What is the minimum credit score for a personal loan?"
.\.venv\Scripts\python.exe -m crag.cli ask "What is the current US federal funds rate?"   # triggers web fallback
```

## Tests (no key needed — LLM and embeddings are mocked)

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Layout

```
src/crag/        config, state (CRAGState), llm, ingest, graph (build_graph + decide), cli
src/crag/nodes/  retrieve, grade (GradeDecision), generate, transform_query, web_search
tests/           19 mocked tests; decide() routing covered exhaustively
data/corpus/     sample lending docs — replace with your own
eval/            M5 harness: eval_set.jsonl + run_eval.py (ragas; not yet run)
docs/            PRD, ARCHITECTURE, AGENTS, SKILLS, rules/
.claude/         agent + skill definitions (the build harness)
ledger/          per-session logs, errors, learnings, handoff
```

## Milestones
M0 setup+smoke · M1 naive baseline · M2 per-chunk grader · M3 LangGraph graph · M4 correction path
(structural stop condition) · M5 ragas eval. See `docs/PRD.md`.

> Honesty rule: the M5 eval has not been run yet, so no measured metric is claimed. Run
> `python eval/run_eval.py` (after `pip install -r requirements-eval.txt`) to earn the number.
