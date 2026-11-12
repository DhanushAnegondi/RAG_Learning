# Eval set design

## Row schema (JSONL)
| Field | Meaning |
|---|---|
| `id` | Stable unique id |
| `question` | What the user asks |
| `ground_truth` | Short reference answer; for unanswerable rows, the expected refusal |
| `category` | `exact_term`, `semantic`, `out_of_corpus`, `unanswerable` |
| `evidence` | Short substrings that must appear in a retrieved chunk; empty for out_of_corpus and unanswerable |
| `expected_route` | `local`, `web` or `abstain` |

## Categories
| Category | Tests | Typical winner |
|---|---|---|
| exact_term | Identifier or number lookup (fee codes, form numbers) | BM25 / hybrid |
| semantic | Paraphrased question, no shared keywords | Dense / hybrid |
| out_of_corpus | Answerable only from the web | Web fallback |
| unanswerable | Plausible but undocumented, web cannot settle it | Abstain |

## Evidence labels
- Evidence is a substring, not a chunk id, so labels survive re-chunking.
- Choose strings that identify the fact (a fee amount with its code), not generic words.
- Hit means some retrieved chunk contains every required substring (or the stated subset rule).

## Hygiene
- Balance categories; do not let one dominate the averages. Report per-category numbers.
- Include distractors: similar numbers for different products, near-duplicate sections.
- Write ground truth from the corpus document, not from a model.
- Freeze the set before comparing systems; changing it mid-comparison voids the comparison.
- Synthetic corpus is labeled synthetic in its README.
