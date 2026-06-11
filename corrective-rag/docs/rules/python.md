# Python rules

## Package structure
- One responsibility per module: `state`, `config`, `llm`, `ingest`, `graph`, `cli`; nodes live under `nodes/`.
- Use relative imports within the package (`from .config import get_settings`, `from ..state import CRAGState`).
- Expose the public surface through `__init__.py` only when callers need it; internal helpers stay private.

## Typing
- State is `CRAGState(TypedDict, total=False)`; all fields optional so partial updates compose.
- `grades` is `List[bool]` — not `list[str]`, not `"yes"`/`"no"` strings.
- Annotate every function signature; avoid `Any` except at true boundaries.

## Configuration
- All settings live in one frozen dataclass `Settings` in `config.py`; call `get_settings()` to read.
- `get_settings()` reads env each call — it does NOT raise at import time if `NVIDIA_API_KEY` is absent.
  Tests import the package with no key set; the CLI is the only place that validates the key and exits 2.
- Access the relevance threshold as `get_settings().relevance_threshold`; its env var is `CRAG_RELEVANCE_THRESHOLD`; default `2`.

## Pydantic models
- Structured-output schemas are `BaseModel` subclasses with `Field(description=...)` on every field.
- Keep them small: `GradeDecision` has exactly one field, `relevant: bool`.
- Do not put LangChain logic inside the model; models are pure data contracts.

## Error handling
- Validate early in CLI entry points; raise informative messages before any network call.
- Do not swallow exceptions inside nodes; let LangGraph surface them so the caller can retry.

## Testing
- All tests run offline: mock LLM calls, vector stores, and web search via `conftest.py` fakes.
- Pure functions (`decide`, `chunk_documents`) are tested without any mock at all.
- Never call `build_graph()` at module level in tests; call it inside the test function.

## Style
- Terse docstrings on public functions only; nodes and helpers are self-explanatory by name.
- The CLI may `print()` (it is the user surface); library/node code does not print.
- Match surrounding code: naming, comment density, import order (`stdlib` → `third-party` → `local`).
