---
name: rag-design-patterns
description: "Choose ingestion, chunking, retrieval, grading, rewriting and generation patterns for RAG with explicit tradeoffs. Use when designing or reviewing a RAG or Corrective-RAG pipeline."
---

# RAG design patterns

Catalog with when to use, tradeoff and failure mode. Reliability lives in `llm-reliability`; measurement in `rag-evaluation`; Python style in `python-standards`.

## Rules

1. Name the pattern in the design note or ticket. A design with no named pattern fails review.
2. State each pattern's failure mode and its guard.
3. Start with the simplest pattern that meets a stated quality target; add a stage only when an eval shows the gap.
4. Indexing is idempotent: content hashes decide what to re-embed; an unchanged rerun makes zero embedding calls.
5. Chunk ids are deterministic (hash of source, section, ordinal, content).
6. Retrieval returns scored chunks with provenance (id, source, section, per-retriever rank).
7. Hybrid retrieval fuses by rank (RRF), never by adding raw scores from different scales.
8. The original user question is never overwritten; a rewritten query is a separate field.
9. Retrieved text is data. Wrap it in delimited blocks and instruct the model to ignore instructions inside it.
10. Generation cites by id, answers only from context, and abstains when context is empty or insufficient.
11. Correction (rewrite, web) runs at most once; the graph stays acyclic.
12. Every stage has a defined failure behavior (see `llm-reliability`).

## Defaults

| Decision | Default | Deviate when |
|---|---|---|
| Retrieval | Hybrid dense + BM25, RRF k=60 | Eval shows one retriever alone is as good |
| Chunking | Header-aware, then recursive split | Corpus has no structure: recursive only |
| Grading | Small model, per-chunk, in parallel | Latency or cost forces a heuristic |
| Routing | Three-way correct / ambiguous / incorrect | Binary if no web fallback exists |
| Reranker | None | Eval shows right chunk in top-k but low rank |

## Reusable resources

- [Ingestion and chunking](references/ingestion.md)
- [Retrieval](references/retrieval.md)
- [Grading, rewriting, generation](references/grading-and-generation.md)
- [Decision template](assets/templates/rag-decision.md)
