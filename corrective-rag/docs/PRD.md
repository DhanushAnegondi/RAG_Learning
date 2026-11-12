# Corrective RAG - product requirements

## Problem

Naive RAG feeds the top-k chunks to the model whatever their quality. Two failures follow:

1. Silent irrelevance: chunks that look similar but do not answer the question produce hedged or invented answers.
2. No fallback: when the corpus has no coverage, the pipeline answers anyway, with no signal to the user.

## Approach

Grade every retrieved chunk, route on the result (CRAG three-way verdict), correct at most once with
a web search, cite sources, and abstain when nothing grounded is left. The correction path is
acyclic by graph topology.

## Goal

A tested, runnable CRAG pipeline (package, CLI, HTTP API, container) plus an eval harness that
compares it with the original version, with no metric published unless a recorded run produced it.

### Non-goals

- Multi-tenant platform, auth or user accounts.
- Providers other than NVIDIA NIM; web search other than DuckDuckGo.
- Streaming answers, long-lived conversation memory.
- Aspirational benchmarks: only measured numbers go in `eval/RESULTS.md`.

## Milestones

| Milestone | Scope | Status |
|---|---|---|
| M0-M5 (v0) | Scaffold, state/config, ingest, grade, generate, two-way routing with query rewrite and web fallback. Frozen at tag `v0-baseline`. | done |
| v1 core | Validated settings, error taxonomy, `LLMClient` (retries, fallback chain, budget), observability traces, three-way routing, the original question never overwritten | implemented |
| v1 retrieval and ingest | Hybrid BM25 + dense with RRF, header-aware chunking, incremental indexer with manifest | implemented |
| v1 answers | Numbered citations, abstention, prompt-injection hygiene, `Answer` that never raises on runtime faults | implemented |
| v1 surfaces | FastAPI (`/v1/ask`, `/healthz`, `/readyz`), CLI, Dockerfile | implemented |
| v1 tests and CI | Offline tests with fakes, ruff, offline chaos smoke and gate, manual live-eval job | implemented |
| Eval harness | Eval set and corpus, v0 vs v1 adapters, fault injector, judge, report | implemented; offline chaos recorded |
| Live quality eval | hit@k, MRR, correctness, faithfulness, routing, abstention for v0 and v1 | measured 2026-11-11; see `eval/RESULTS.md` (web search partly unavailable during the run) |

## Acceptance

- `pytest` passes with `NVIDIA_API_KEY` unset.
- Offline chaos run: crash rate 0 and error recovery rate 1.0 for v1 (enforced in CI).
- README numbers match `eval/RESULTS.md`; anything not run is labelled not run.
