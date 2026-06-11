# RAG best practices

## Retrieval
- Vector store: Chroma, persisted to `Settings.persist_dir`; opened by `get_vectorstore()`.
- Embeddings: `NVIDIAEmbeddings(model=Settings.embed_model, truncate="END")`; `input_type` is set automatically per call (query vs passage).
- Retrieve top-`k` chunks where `k = Settings.top_k` (default 4); do not hard-code.

## Ingestion
- `load_documents(corpus_dir)` reads `.md`, `.txt`, and `.pdf` from `Settings.corpus_dir`.
- `chunk_documents(docs, chunk_size=1000, chunk_overlap=150)` uses `RecursiveCharacterTextSplitter`.
  These values are the project defaults; do not change them without updating tests.
- `build_index()` embeds chunks and persists the store; re-running rebuilds from the corpus.
- Chunking is a pure function — unit-testable with no API key.

## Grading (per-chunk relevance)
- Grade each retrieved chunk independently: one LLM call per document.
- Grader schema: `GradeDecision(BaseModel)` with one field `relevant: bool`.
- Use `get_llm().with_structured_output(GradeDecision)` — do not parse free-text `"yes"`/`"no"` strings.
- Per-chunk grading lets the graph drop irrelevant chunks individually rather than discarding the entire result set.

## Relevance threshold
- `decide()` compares the count of `True` grades against `Settings.relevance_threshold` (default 2).
- Raising the threshold makes the system more likely to fall back to web search.
- Configure via `CRAG_RELEVANCE_THRESHOLD` env var; no code change needed.

## Web fallback
- Web search uses `duckduckgo-search`; no API key required.
- Results are stored in `state["web_results"]` separate from `state["documents"]`.
- The fallback runs at most once — enforced by graph topology, not a flag.
- Do not use Tavily, OpenAI, or any key-gated search provider.

## LLM
- `get_llm()` returns `ChatNVIDIA(model=Settings.llm_model, temperature=0)`.
- Model default: `meta/llama-3.3-70b-instruct`. Provider: NVIDIA AI Endpoints (`langchain-nvidia-ai-endpoints`).
- `temperature=0` for grading and generation to keep outputs deterministic in tests.
- No OpenAI or Anthropic SDK anywhere in this project.

## Generation
- `generate` uses only chunks graded relevant (plus any `web_results`) as context before prompting.
- Write the final answer to `state["generation"]` and append `"generate"` to `state["steps"]`.

## Hallucination guardrails
- The generation prompt instructs the model to answer ONLY from the provided context and to say it does not know when the context is insufficient.
- Do not tell the model to "use its own knowledge" — that unlocks hallucination.

## Offline testing
- `FakeLLM` in `conftest.py` returns deterministic structured output without a key.
- `FakeStore` simulates similarity search with fixed `Document` objects.
- `FakeDDGS` simulates DuckDuckGo results.
- All 19 tests pass with `NVIDIA_API_KEY` unset.

## Evaluation honesty (M5)
- The ragas harness (`eval/run_eval.py`) compares naive RAG vs CRAG on faithfulness and context precision.
- It has NOT been run yet. Report no metric until it is — the resume bullet stays qualitative until then.
