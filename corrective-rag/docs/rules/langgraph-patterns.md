# LangGraph patterns

## Graph factory
- `build_graph()` is a factory function, not a module-level object.
  Call it once in the CLI or test; do not import a pre-compiled `app` or `graph` from `graph.py`.
- Inside the factory: add every node, set the entry point, add edges, then call `.compile()` and return.

## Node contract
- A node is a plain function `(state: CRAGState) -> dict`.
- It returns only the keys it modifies; LangGraph merges the return dict into state.
- Append to `steps` inside every node: `state.get("steps", []) + ["<node_name>"]`.
- Node names in the graph: `retrieve`, `grade`, `generate`, `transform_query`, `web_search`.

## Conditional edge — `decide`
- `decide(state) -> str` is a **pure function**: reads `state["grades"]`, returns a node name string, mutates nothing.
- Logic: count `True` values in `grades`; return `"generate"` if count >= `get_settings().relevance_threshold` (default 2), else `"transform_query"`.
- Register it with `add_conditional_edges("grade", decide, {"generate": "generate", "transform_query": "transform_query"})`.
- The mapping keys must be the exact strings `decide` returns.

## Stop condition
- The correction path terminates by **topology**: `transform_query -> web_search -> generate -> END`.
- There is no loop-back edge from `web_search` or `generate` to `grade`.
- Do not add a `web_search_done` flag or any runtime guard; the graph structure enforces at-most-one correction.

## State design
- `CRAGState` uses `total=False` so nodes can return partial dicts.
- `grades: List[bool]` is parallel to `documents`: `grades[i]` is the relevance verdict for `documents[i]`.
- `web_results: List[Document]` is separate from `documents`; `generate` merges both.

## Edge map
```
retrieve -> grade
grade    -> decide() -> generate | transform_query
transform_query -> web_search
web_search      -> generate
generate        -> END
```
No other edges exist. Do not add edges without updating this map and the tests.

## Testing the graph
- Patch node dependencies (e.g. `crag.nodes.retrieve.get_vectorstore`) before calling `build_graph()`.
- Test `decide` in isolation with hand-crafted `CRAGState` dicts — no graph compilation needed.
- `test_graph.py` exercises the full compiled graph with the fakes from `conftest.py`.
