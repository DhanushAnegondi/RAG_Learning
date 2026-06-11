# Architecture

Corrective RAG (CRAG) is a LangGraph state machine that self-corrects retrieval quality before generating an answer. It ships five nodes and one conditional edge. The interview signal is explaining `decide()` edge-by-edge.

---

## Graph topology

```
                        +----------+
                        | retrieve |
                        +----+-----+
                             |
                        +----v-----+
                        |  grade   |
                        +----+-----+
                             |
               [decide() conditional edge]
              /                            \
   n_relevant >= threshold          n_relevant < threshold
             /                                \
    +--------v------+              +----------v--------+
    |   generate    |              | transform_query   |
    +--------+------+              +----------+--------+
             |                               |
            END                    +---------v--------+
                                   |    web_search    |
                                   +---------+--------+
                                             |
                                   +---------v--------+
                                   |    generate      |
                                   +---------+--------+
                                             |
                                            END
```

The correction path (`transform_query -> web_search -> generate -> END`) is structurally terminal. There is no back-edge to `grade` and no flag like `web_search_done`. The corrective loop runs at most once by topology.

---

## `CRAGState` schema

| Key | Type | Written by | Read by |
|---|---|---|---|
| `question` | `str` | caller (entry) | `retrieve`, `grade`, `transform_query`, `generate` |
| `documents` | `List[Document]` | `retrieve` | `grade`, `generate` |
| `grades` | `List[bool]` | `grade` | `decide()` |
| `web_results` | `List[Document]` | `web_search` | `generate` |
| `generation` | `str` | `generate` | caller (output) |
| `steps` | `List[str]` | every node (appends its own name) | CLI (prints as "Route:") |

`grades` is `List[bool]`, one entry per chunk — parallel to `documents`. It is never `"yes"`/`"no"` strings. This per-chunk granularity is intentional: a whole-set grade cannot tell you which chunk to drop.

`total=False` on the TypedDict means all keys are optional at construction time; nodes add keys as they run.

---

## `build_graph()` wiring

`build_graph()` is a factory function. It is called to produce a compiled graph; there is no module-level `app` or `graph` singleton. This keeps the graph testable (each test gets a fresh compile) and avoids import-time side effects.

```python
def build_graph():
    g = StateGraph(CRAGState)

    g.add_node("retrieve",        retrieve)
    g.add_node("grade",           grade_documents)
    g.add_node("generate",        generate)
    g.add_node("transform_query", transform_query)
    g.add_node("web_search",      web_search)

    g.set_entry_point("retrieve")

    g.add_edge("retrieve",        "grade")
    g.add_conditional_edges(
        "grade", decide,
        {"generate": "generate", "transform_query": "transform_query"}
    )
    g.add_edge("transform_query", "web_search")
    g.add_edge("web_search",      "generate")
    g.add_edge("generate",        END)

    return g.compile()
```

Node names are the string keys above. The registered name for `grade_documents` is `"grade"`.

---

## `decide()` — why it is pure

```python
def decide(state) -> str:
    n_relevant = sum(1 for g in state.get("grades", []) if g)
    threshold = get_settings().relevance_threshold  # default 2
    return "generate" if n_relevant >= threshold else "transform_query"
```

`decide()` reads `state["grades"]` and returns a node name string. It does not write to state, has no side effects, and does not call any LLM. LangGraph requires conditional-edge functions to be pure: the router must be a deterministic mapping from state to the next node name so the graph can introspect and compile the edge map. Mutation inside a conditional edge would be invisible to the graph runtime and break reproducibility.

The threshold is `Settings.relevance_threshold` (env `CRAG_RELEVANCE_THRESHOLD`, default `2`). It is not a module-level constant.

---

## Structural stop condition

The graph has no cycle. The two paths through it are:

- Happy path: `retrieve -> grade -> generate -> END`
- Correction path: `retrieve -> grade -> transform_query -> web_search -> generate -> END`

Both terminate at `END`. There is no edge from `web_search` or `generate` back to `grade`. The corrective branch runs at most once regardless of whether web results are relevant. This is a deliberate design constraint: the alternative (looping back to `grade`) would require a termination guard (a flag, a counter, or a visited-set) and makes the graph harder to reason about. The structural guarantee is self-documenting.

---

## NVIDIA AI Endpoints

All LLM and embedding calls go through `langchain-nvidia-ai-endpoints`. There is no OpenAI, Anthropic, or Tavily dependency.

### `get_llm()`

```python
ChatNVIDIA(model=llm_model, temperature=0)
```

Default model: `meta/llama-3.3-70b-instruct`. Temperature 0 for deterministic grading and generation.

### `get_embeddings()`

```python
NVIDIAEmbeddings(model=embed_model, truncate="END")
```

Default model: `nvidia/nv-embedqa-e5-v5`. `truncate="END"` instructs the endpoint to drop tokens from the tail when a chunk exceeds the model's context window, rather than raising an error. The `input_type` (query vs. passage) is set automatically by the endpoint based on call context; it does not need to be specified explicitly.

### Structured-output grader

```python
class GradeDecision(BaseModel):
    relevant: bool = Field(description="True iff the document helps answer the question.")

grader = get_llm().with_structured_output(GradeDecision)
```

`GradeDecision` has exactly one field: `relevant: bool`. The grader is invoked once per chunk so that irrelevant chunks can be identified individually. A single call over all chunks would return one verdict for the whole set, making it impossible to know which chunks to drop.

---

## Web fallback

When `decide()` routes to `transform_query`, the query is rewritten and passed to `web_search`, which uses `duckduckgo-search` (no API key required). Results are returned as `List[Document]` and merged into `web_results` in state. `generate` reads both `documents` and `web_results`.

---

## Configuration

`get_settings()` reads environment variables on every call (no caching). It does not raise if `NVIDIA_API_KEY` is absent, so tests can import the module without a key. The CLI checks the key at startup and exits with code 2 and a message if it is missing.

| Setting | Env var | Default |
|---|---|---|
| `nvidia_api_key` | `NVIDIA_API_KEY` | — |
| `llm_model` | `CRAG_LLM_MODEL` | `meta/llama-3.3-70b-instruct` |
| `embed_model` | `CRAG_EMBED_MODEL` | `nvidia/nv-embedqa-e5-v5` |
| `top_k` | `CRAG_TOP_K` | `4` |
| `relevance_threshold` | `CRAG_RELEVANCE_THRESHOLD` | `2` |
| `persist_dir` | `CRAG_PERSIST_DIR` | _(project default: `chroma_store/`)_ |
| `corpus_dir` | `CRAG_CORPUS_DIR` | `data/corpus` |
