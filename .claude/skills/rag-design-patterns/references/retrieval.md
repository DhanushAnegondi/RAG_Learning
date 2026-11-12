# Retrieval

| Method | Wins on | Loses on | Notes |
|---|---|---|---|
| Dense (embeddings) | Paraphrase, semantic questions | Exact ids, codes, rare terms, numbers | Needs the embedding API at query time |
| BM25 (lexical) | Exact terms (`FEE-NSF-02`, form numbers) | Synonyms, paraphrase | No API; cheap fallback when embeddings are down |
| Hybrid (RRF) | Mixed workloads | Slightly more latency | Default |
| Reranker | Right chunk retrieved but ranked low | Adds latency and a model | Add only if eval shows a rank problem |

## Reciprocal rank fusion
`score(d) = sum over retrievers of 1 / (k + rank_r(d))`, rank starting at 1, `k` about 60. Rank-based, so no score normalization is needed. Fetch more candidates than you return (`fetch_k` > `top_k`). Dedupe by chunk id after fusion.

## Guards
- One retriever fails: serve the other and mark the result degraded.
- Distractors (similar numbers for different products): keep product or section context in the chunk, and test with such cases.
- BM25 tokenizer lowercases and splits on alphanumerics; make sure hyphenated identifiers stay matchable (test it).

## Verify
Unit test RRF math on a hand-computed example; a BM25 exact-term case where dense is faked to miss; mode switch (dense, bm25, hybrid) changes results as expected.
