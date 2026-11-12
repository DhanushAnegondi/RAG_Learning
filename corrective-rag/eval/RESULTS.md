# Evaluation results

Generated 2026-11-11 22:52 UTC by `python -m eval.report` from the latest recorded run of each (system, suite, mode). Anything not run is marked "not run"; no number here is estimated.

**Limits:** the eval set has 40 questions (6 to 14 per category), so differences of a few points are within noise; per-category cells rest on very few rows.

## Quality (live models)

| Metric | v0 (before) | v1 (after) |
|---|---|---|
| Retrieval hit@1 | 64.3% | 78.6% |
| Retrieval hit@k | 85.7% | 100.0% |
| MRR | 0.73 | 0.86 |
| Answer correctness, exact_term + semantic (LLM judge) | 60.7% | 67.9% |
| Key-fact match, exact_term + semantic (deterministic) | 89.5% | 81.8% |
| Web answer rate, out_of_corpus (LLM judge) | 0.0% | 0.0% |
| Web answer judge failures (excluded from the rate) | 0 | 0 |
| Faithfulness (LLM judge) | 96.7% | 96.2% |
| Routing accuracy (exact) | 50.0% | 77.5% |
| Routing accuracy (lenient) | 50.0% | 82.5% |
| Abstention accuracy, unanswerable (judge-assisted) | 16.7% | 100.0% |
| False-abstention rate, in-corpus (judge-assisted) | 0.0% | 3.6% |
| Abstention accuracy, structural flag/regex | 16.7% | 100.0% |
| False-abstention rate, structural flag/regex | 0.0% | 3.6% |
| Crash rate | 17.5% | 0.0% |
| Web search unavailable (failed or skipped), share of q | 17.5% | 55.0% |
| Judge failures (rows) | 2 | 0 |
| Latency p50 (ms) | 12473 | 2774 |
| Latency p95 (ms) | 23978 | 8522 |
| Provider LLM calls / q (chat + structured, every attempt) | 9.50 | 9.30 |
| Provider embedding calls / q | 1.00 | 1.00 |
| Logical LLM calls / q (v1 only) | n/a | 5.08 |

> Web search (DuckDuckGo, free, no key) was unavailable for part of these runs (v0 17.5%, v1 55.0% of questions). v0 crashes on that; v1 records it, opens its circuit breaker and answers from local documents or abstains. Only retrieval (hit@k, MRR) is independent of the web. Crash rate, routing, correctness, abstention, web answer rate and latency all carry the outage: v0's web crashes are scored as wrong answers, and in-corpus questions with the web unavailable (v0 4, v1 10) lost the web fallback.

### Per category

| Category | v0 hit@k | v0 MRR | v0 correct | v0 routing | v0 abstained | v1 hit@k | v1 MRR | v1 correct | v1 routing | v1 abstained |
|---|---|---|---|---|---|---|---|---|---|---|
| exact_term | 85.7% | 0.74 | 71.4% | 42.9% | n/a | 100.0% | 0.92 | 78.6% | 100.0% | n/a |
| out_of_corpus | n/a | n/a | n/a | 100.0% | n/a | n/a | n/a | n/a | 0.0% | n/a |
| semantic | 85.7% | 0.72 | 50.0% | 50.0% | n/a | 100.0% | 0.81 | 57.1% | 78.6% | n/a |
| unanswerable | n/a | n/a | n/a | 16.7% | 16.7% | n/a | n/a | n/a | 100.0% | 100.0% |

## Ablation: grader model (v1 only)

| Metric | grader `nvidia/nemotron-3.5-bolt-e4b` (default) | grader `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` |
|---|---|---|
| Answer correctness | 67.9% | 71.4% |
| Key-fact match | 81.8% | 81.8% |
| Faithfulness | 96.2% | 93.1% |
| Routing accuracy (exact) | 77.5% | 82.5% |
| False-abstention rate | 3.6% | 0.0% |
| Web search unavailable | 55.0% | 30.0% |
| Retries / q | 0.03 | 1.20 |
| Provider LLM calls / q | 9.30 | 15.70 |
| Latency p50 (ms) | 2774 | 7691 |
| Latency p95 (ms) | 8522 | 31269 |

Web was unavailable for 55.0% vs 30.0% of questions in these two runs, so differences of a few points in correctness or routing are within noise and confounded by the outage. The cost rows (retries, provider calls, latency) are the clearer signal of the grader choice.

Ablation file: `results/_ablation/v1_quality_live_20261111T224656857903Z.json`.

## Chaos, offline (fake models; robustness only, no answer quality)

| Fault rate | System | Faulted q | Recovery rate | Clean among faulted | Crash rate | Answered | Abstained | Degraded | Retries / q | Provider LLM calls / q | Embed calls / q | Logical LLM calls / q (v1) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | v0 | 0 | n/a | n/a | 0.0% | 100.0% | 0.0% | 0.0% | 0.00 | 5.70 | 1.00 | n/a |
| 0 | v1 | 0 | n/a | n/a | 0.0% | 100.0% | 0.0% | 0.0% | 0.00 | 6.35 | 1.00 | 6.35 |
| 0.05 | v0 | 15 | 0.0% | 0.0% | 37.5% | 62.5% | 0.0% | 0.0% | 0.00 | 4.60 | 1.00 | n/a |
| 0.05 | v1 | 11 | 100.0% | 54.5% | 0.0% | 100.0% | 0.0% | 12.5% | 0.17 | 6.58 | 1.00 | 6.35 |
| 0.1 | v0 | 22 | 0.0% | 0.0% | 55.0% | 45.0% | 0.0% | 0.0% | 0.00 | 3.95 | 1.00 | n/a |
| 0.1 | v1 | 16 | 100.0% | 56.2% | 0.0% | 100.0% | 0.0% | 17.5% | 0.50 | 6.90 | 1.00 | 6.33 |
| 0.3 | v0 | 38 | 0.0% | 0.0% | 95.0% | 5.0% | 0.0% | 0.0% | 0.00 | 2.15 | 1.00 | n/a |
| 0.3 | v1 | 37 | 100.0% | 48.6% | 0.0% | 87.5% | 12.5% | 47.5% | 2.08 | 8.38 | 1.00 | 5.78 |

## Chaos, live (real models and web)

not run for either system.

> Footnote: v1's recovery rate is 100% by contract (`pipeline.answer` never raises), so it says little
> by itself. The informative columns are *clean among faulted*, *abstained* and *degraded*. v0 has no
> degraded flag (always 0%) and no retry counter.

## Run metadata

| Run | Commit / dirty / src hash | Models | Corpus hash | Eval-set hash | Rate / seed | Time (UTC) | File |
|---|---|---|---|---|---|---|---|
| v0 chaos (offline), n=40, network blocked | `f2b924c029` dirty=False src `aeb1a4d3a3` | fakes (configured names not called) | `e2f8b2e92f5d` | `3bacc920a1fe` | 0.0 / 7 | 2026-11-11T22:50:03+00:00 | `results/v0_chaos_offline_r0_20261111T225003565311Z.json` |
| v1 chaos (offline), n=40, network blocked | `f2b924c029` dirty=True src `04cdbe2edb` | fakes (configured names not called) | `e2f8b2e92f5d` | `3bacc920a1fe` | 0.0 / 7 | 2026-11-11T22:50:10+00:00 | `results/v1_chaos_offline_r0_20261111T225010791494Z.json` |
| v0 chaos (offline), n=40, network blocked | `f2b924c029` dirty=False src `aeb1a4d3a3` | fakes (configured names not called) | `e2f8b2e92f5d` | `3bacc920a1fe` | 0.05 / 7 | 2026-11-11T22:50:03+00:00 | `results/v0_chaos_offline_r0.05_20261111T225003646320Z.json` |
| v1 chaos (offline), n=40, network blocked | `f2b924c029` dirty=True src `04cdbe2edb` | fakes (configured names not called) | `e2f8b2e92f5d` | `3bacc920a1fe` | 0.05 / 7 | 2026-11-11T22:50:10+00:00 | `results/v1_chaos_offline_r0.05_20261111T225010876220Z.json` |
| v0 chaos (offline), n=40, network blocked | `f2b924c029` dirty=False src `aeb1a4d3a3` | fakes (configured names not called) | `e2f8b2e92f5d` | `3bacc920a1fe` | 0.1 / 7 | 2026-11-11T22:50:03+00:00 | `results/v0_chaos_offline_r0.1_20261111T225003724043Z.json` |
| v1 chaos (offline), n=40, network blocked | `f2b924c029` dirty=True src `04cdbe2edb` | fakes (configured names not called) | `e2f8b2e92f5d` | `3bacc920a1fe` | 0.1 / 7 | 2026-11-11T22:50:10+00:00 | `results/v1_chaos_offline_r0.1_20261111T225010956290Z.json` |
| v0 chaos (offline), n=40, network blocked | `f2b924c029` dirty=False src `aeb1a4d3a3` | fakes (configured names not called) | `e2f8b2e92f5d` | `3bacc920a1fe` | 0.3 / 7 | 2026-11-11T22:50:03+00:00 | `results/v0_chaos_offline_r0.3_20261111T225003803208Z.json` |
| v1 chaos (offline), n=40, network blocked | `f2b924c029` dirty=True src `04cdbe2edb` | fakes (configured names not called) | `e2f8b2e92f5d` | `3bacc920a1fe` | 0.3 / 7 | 2026-11-11T22:50:11+00:00 | `results/v1_chaos_offline_r0.3_20261111T225011035275Z.json` |
| v0 quality (live), n=40 | `f2b924c029` dirty=False src `aeb1a4d3a3` | gen `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`, grader `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`, embed `nvidia/nemotron-3.5-embed-1b`, judge `deepseek-ai/deepseek-v4.1-flash` | `e2f8b2e92f5d` | `3bacc920a1fe` | - / 7 | 2026-11-11T21:27:20+00:00 | `results/v0_quality_live_20261111T212720930965Z.json` |
| v1 quality (live), n=40 | `f2b924c029` dirty=True src `04cdbe2edb` | gen `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`, grader `nvidia/nemotron-3.5-bolt-e4b`, embed `nvidia/nemotron-3.5-embed-1b`, judge `deepseek-ai/deepseek-v4.1-flash` | `e2f8b2e92f5d` | `3bacc920a1fe` | - / 7 | 2026-11-11T21:59:30+00:00 | `results/v1_quality_live_20261111T215930974428Z.json` |

## What each metric means

- **hit@k** - share of questions (that have labelled evidence) where the evidence text shows up in the
  top k retrieved chunks. Measures retrieval alone, before any LLM writes anything.
- **MRR** - mean of 1/rank of the first chunk set that contains the evidence (1.0 = always first, 0 = never found).
- **Answer correctness** - exact_term + semantic rows only. A judge model (different from the generator,
  temperature 0) checks the answer against the written ground truth; an abstention counts as wrong.
- **Web answer rate** - out_of_corpus rows only (the corpus cannot answer them; a web source should).
  A judge checks for a specific, on-topic, non-abstaining fact attributed to a web source with no
  fabrication about the fictional lender. It cannot verify the live value, so it is not "correctness".
- **Key-fact match** - deterministic check: are the numbers/identifiers from the ground truth present in the answer?
- **Faithfulness** - judge: what fraction of the answer's claims are supported by the context it was given.
- **Routing accuracy** - did the system take the expected path (local / web / abstain)? *Exact* needs an
  identical label; *lenient* also accepts `local+web` where `local` or `web` was expected. A crash is a miss.
- **Abstention accuracy** - on unanswerable questions (scored by abstention only), how often it declined
  instead of guessing. The primary figure uses one judge question for both systems ("does the answer
  decline or say it doesn't know?"); the structural variant (v1's `abstained` flag, v0's regex) is
  shown separately.
- **False-abstention rate** - on questions the corpus can answer, how often it wrongly refused.
- **Crash rate** - share of questions where the pipeline raised instead of returning something.
- **Clean among faulted** - of the faulted questions, the share that returned a real answer, not
  degraded and not an abstain. This is the informative column for v1.
- **Error recovery rate** - among questions where at least one provider fault was injected (timeout, 429,
  500, empty structured output, embeddings down, web down), the share that finished without crashing and
  returned a usable answer or an explicit abstain. The fault rate is per provider call, so a question
  that makes many calls is very likely to be hit at least once.
- **Answered / Abstained / Degraded** (chaos tables, share of all questions) - returned a real answer;
  returned an explicit "I don't know"; or finished but flagged `degraded` (a fallback or reduced path was
  used). v0 has no degraded flag, so it always shows 0%.
- **Retries / q** - provider retries per question (v0 has none). The fault-rate 0 row is the control:
  nothing is injected, so it shows whether each system works with the fakes at all.
- **Offline chaos** uses fake models and a blocked network, so it measures robustness only, never answer quality.
- **Provider LLM calls** - every chat and structured-output attempt sent to the provider, retries and
  fallbacks included, counted at the same boundary for both systems; embedding calls are counted
  separately. **Logical LLM calls** is v1's own pipeline counter (one per logical call, before retries)
  and is not comparable with v0. Latency is wall-clock p50/p95.
- **Judge failures** - rows where a judge call failed or returned unparseable JSON twice; those fields
  are left empty (not scored as 0) and counted here.
