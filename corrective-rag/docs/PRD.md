# Corrective RAG (CRAG) — product requirements

## Problem

Naive RAG retrieves the top-k chunks from a vector store and feeds them directly to the LLM. It fails in two predictable ways:

1. **Silent irrelevance.** The retriever returns chunks that score well on embedding similarity but do not actually answer the question. The LLM receives noisy context and either hallucinates an answer or hedges uselessly.
2. **No fallback path.** When the local corpus lacks coverage, the pipeline has no mechanism to broaden the search. The answer is simply wrong, with no signal to the user.

Both failures are invisible to the user and undetectable without an explicit grading step.

## Why CRAG

Corrective RAG inserts a relevance-grading step after retrieval and routes the pipeline based on the verdict:

- If enough chunks are relevant, generate directly.
- If not, rewrite the query and fall back to a web search before generating.

The correction path runs at most once, by graph topology. There is no polling loop, no flag, and no ambiguity about when the pipeline stops.

The interview signal is the `decide()` function: a five-line pure function that reads a list of booleans and returns a node name. Explaining every edge of that conditional is the entire architecture story.

---

## Goal

Ship a working, testable CRAG pipeline as a Python package with a CLI. The primary deliverable is a portfolio artifact that demonstrates production-grade LangGraph state machine design to a hiring panel.

### Non-goals

- A multi-tenant platform or API server.
- More than five LangGraph nodes or three skills.
- Any LLM provider other than NVIDIA NIM (no OpenAI, no Anthropic, no Tavily).
- A UI, dashboard, or persistent user accounts.
- Retrieval strategies beyond Chroma + DuckDuckGo fallback.
- Unmeasured quality metrics or aspirational benchmarks.

---

## The one user

A recently-hired data engineer building a resume portfolio project. Needs a self-contained, explainable RAG system that runs on Windows/PowerShell with a free NVIDIA NIM API key. Will demo it in interviews by walking through the `decide()` edge logic. Cares about correctness of the code path, not scale or latency.

---

## Functional requirements by milestone

### M0 — repo scaffold

- `pyproject.toml` with `crag` console script entry point.
- `src/crag/` package layout: `state.py`, `config.py`, `llm.py`, `ingest.py`, `graph.py`, `cli.py`, `nodes/` directory.
- `tests/` with `conftest.py` fakes (`FakeLLM`, `FakeStore`, `FakeDDGS`).
- All imports resolve; `pytest` collects with no errors.

### M1 — state and config

- `CRAGState` TypedDict (total=False) with fields: `question: str`, `documents: List[Document]`, `grades: List[bool]`, `web_results: List[Document]`, `generation: str`, `steps: List[str]`.
- `Settings` frozen dataclass with fields: `nvidia_api_key`, `llm_model`, `embed_model`, `top_k`, `relevance_threshold`, `persist_dir`, `corpus_dir`.
- `get_settings()` reads environment on every call; does NOT raise if `NVIDIA_API_KEY` is absent (so tests run offline).
- Defaults: `llm_model="meta/llama-3.3-70b-instruct"`, `embed_model="nvidia/nv-embedqa-e5-v5"`, `top_k=4`, `relevance_threshold=2`.
- `CRAG_RELEVANCE_THRESHOLD` env var overrides the threshold.

### M2 — grader node

- Pydantic model `GradeDecision` with one field: `relevant: bool`.
- `grade_documents(state)` node: one LLM call per document via `get_llm().with_structured_output(GradeDecision)`. Returns `{"grades": List[bool], "steps": [..., "grade"]}`.
- Per-chunk grading (not whole-set) so the pipeline knows which chunks to drop.
- Registered in the graph under the node name `"grade"`.

### M3 — graph and decide()

- Five nodes: `retrieve`, `grade`, `generate`, `transform_query`, `web_search`.
- `build_graph()` is a factory function (not a module-level compiled object).
- Edge topology:
  - `retrieve` → `grade`
  - `grade` → conditional on `decide()`
  - `transform_query` → `web_search` → `generate` → `END`
  - `generate` → `END` (direct path)
- `decide(state)` is a pure function: reads `state["grades"]`, returns `"generate"` or `"transform_query"`. No state mutation.
- The correction path runs at most once by topology. No loop-back edge from `web_search` or `generate` to `grade`.

### M4 — CLI

- `python -m crag.cli ingest` — builds Chroma index from `data/corpus` (`.md`, `.txt`, `.pdf`).
- `python -m crag.cli ask "<question>"` — runs the graph; prints `Route: retrieve -> grade -> ...` then `Answer: <text>`.
- CLI checks for `NVIDIA_API_KEY` and exits with code 2 and a human-readable message if absent.
- No `--question`, `--top-k`, `--verbose`, `--dry-run` flags, and no `retrieve` subcommand.

### M5 — eval gate + ragas comparison (stretch)

Two layers, in order of importance:

1. **Offline gate (required, done).** 19 tests pass with `NVIDIA_API_KEY` unset (all LLM/store calls mocked). `decide()` is covered exhaustively: zero relevant, below threshold, at threshold, above threshold. `chunk_documents()` is unit-tested without a key. `test_graph` runs a full graph execution end-to-end using fakes.
2. **ragas comparison (stretch, NOT yet run).** `eval/run_eval.py` scores naive RAG vs CRAG with ragas (faithfulness, context precision) over `eval/eval_set.jsonl` (~15 Q/A). Requires `pip install -r requirements-eval.txt` and a live `NVIDIA_API_KEY`. **No metric is claimed until this script is actually run** — the resume bullet stays qualitative until then (honesty rule).

---

## The `decide()` decision contract

This is the architectural core of the project. Every reviewer question about CRAG traces back here.

```python
def decide(state) -> str:
    n_relevant = sum(1 for g in state.get("grades", []) if g)
    threshold = get_settings().relevance_threshold  # default 2
    return "generate" if n_relevant >= threshold else "transform_query"
```

| Input | Type | Description |
|---|---|---|
| `state["grades"]` | `List[bool]` | One entry per retrieved chunk. `True` = relevant. Produced by the `grade` node. |
| `get_settings().relevance_threshold` | `int` | Minimum number of relevant chunks required to skip correction. Default `2`. Controlled by `CRAG_RELEVANCE_THRESHOLD` env var. |

| Output | Meaning |
|---|---|
| `"generate"` | At least `threshold` chunks are relevant. Proceed to answer generation using the retrieved context. |
| `"transform_query"` | Fewer than `threshold` chunks are relevant. Rewrite the query and fall back to web search before generating. |

**Constraints:**

- Pure function. No side effects, no state mutation.
- The field name is `Settings.relevance_threshold`. There is no constant named `MIN_RELEVANT_CHUNKS` or `RELEVANCE_THRESHOLD`.
- `grades` is `List[bool]`, not `List[str]`. The grader produces `True`/`False`, not `"yes"`/`"no"`.
- The correction path (`transform_query → web_search → generate → END`) terminates by topology. There is no `web_search_done` flag and no edge from `generate` back to `grade`.

---

## Success criteria

| Criterion | How measured |
|---|---|
| 19 offline tests pass | `pytest` with `NVIDIA_API_KEY` unset |
| `decide()` covered exhaustively | All four grade-count cases in `test_decide` |
| CLI exits 2 with message on missing key | Manual or test |
| `ask` prints route then answer | Manual smoke test with a real key |
| Ingest handles `.md`, `.txt`, `.pdf` | `test_ingest` with fixture files |
| No module-level LLM calls (safe to import key-free) | Import test in CI |

The M5 offline gate is: all 19 tests green on a machine with no `NVIDIA_API_KEY` set. The M5 ragas comparison is a stretch that earns a measured number only once `eval/run_eval.py` has actually been executed.

---

## Out of scope

Ship the loop, not a platform. The following are explicitly excluded:

- More than five LangGraph nodes.
- A second correction cycle (no loop back to `grade`).
- A second eval framework beyond the optional ragas M5 harness (e.g., LangSmith, TruLens).
- API server, web UI, or authentication.
- Multi-document retrieval strategies (hybrid search, re-ranking, etc.).
- Streaming responses.
- Deployment infrastructure (Docker, cloud, CI beyond local `pytest`).
- Providers other than NVIDIA NIM and DuckDuckGo.
