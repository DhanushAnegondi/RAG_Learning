# Run and compare the two versions

All examples below run from the repository root in PowerShell. Never commit your key or corpus.

## 1. Install once

```powershell
git switch codex/experience-copilot-v2
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r corrective-rag/requirements.txt -r experience-copilot/requirements.txt
.\.venv\Scripts\python.exe -m pip install -e corrective-rag -e experience-copilot
Set-Location experience-copilot
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env and add NVIDIA_API_KEY. Do not overwrite an existing .env.
```

The key is needed only for ingestion/live model calls, not offline tests or question-set validation.
The existing model list was recorded in June 2026; provider availability can change. Choose an
available model with structured-output support. A refusal or unsupported schema blocks V2 drafts.
The old default chat model returned HTTP 410 during the November 2026 check; an available chat
model is still needed for end-to-end answers. The default V2 embedding endpoint was verified live.

## 2. Run offline checks

From `experience-copilot`:

```powershell
..\.venv\Scripts\python.exe -m pytest
..\.venv\Scripts\python.exe -m copilot.cli evaluate
```

Tests use fake models and local test embeddings, including an actual Chroma persistence test.
Passing proves the tested behavior, not factual answer quality. `evaluate` without `--live` validates
the dataset and makes no API calls.

## 3. Run a live synthetic comparison

For retrieval only, with no chat model or generated answers:

```powershell
..\.venv\Scripts\python.exe eval/retrieval_check.py
```

This compares V1 dense retrieval with V2's pre-reranking hybrid candidates at top four on 30
answerable fictional questions. It does not measure coverage, abstention, answer accuracy or the
full V2 reranker. Results are saved to `eval/results/retrieval-live.json`.

```powershell
# Short smoke check first; uses fictional documents, isolated disposable indexes and your NVIDIA key.
..\.venv\Scripts\python.exe -m copilot.cli evaluate --live --limit 4

# All 48 retrieval + evidence-coverage comparisons.
..\.venv\Scripts\python.exe -m copilot.cli evaluate --live --output eval/results/retrieval.json

# Add generated answers and V2 citation/claim checks (more calls and more time).
..\.venv\Scripts\python.exe -m copilot.cli evaluate --live --answers --output eval/results/answers.json
```

Use `--model <available-model-id>` to keep a chosen answer/check model fixed. The embedding model is
`EXP_V2_EMBED_MODEL` (default `nvidia/nemotron-3.5-embed-1b`). The report records both. Each live run builds
fresh fixture indexes under the report's directory; your personal indexes are not used or changed.
Results, generated text and indexes are ignored by Git.

The fictional corpus deliberately includes draft, synthetic and unverified distractors. Its confirmed
files are authoritative only within the fictional benchmark scenario. They are not the user's history.

Read the comparison JSON as follows:

| Field | What it measures |
|---|---|
| `source_recall` | Fraction of expected source files appearing in selected results, on answerable questions |
| `source_mrr` | Reciprocal rank of the first expected source file, on answerable questions |
| `coverage_accuracy` | Coverage decision matches the human-written fixture label; API errors count as failures |
| `correct_abstention_rate` | Unsupported questions correctly marked uncovered; API errors do not earn credit |
| `mean_seconds` | Full selected retrieval/coverage path; with `--answers`, includes generation/checking |
| `model_verified` | V2 model-check outcome when answers are requested; not an independent human correctness score |

V1 is evaluated in fast mode, matching its original UI default: nonempty retrieval is its coverage
proxy. V2 performs additional evidence checks. Source recall/MRR compare their final selected contexts,
not identical search algorithms alone. Inspect individual results before attributing a difference to
hybrid retrieval. The report separately includes held-out questions. Tune on dev questions only;
repeatedly tuning on the holdout makes it no longer held out.

## 4. Prepare YOUR evidence for V2

Keep private documents in `data/corpus/`. Create `data/corpus/evidence.json` using this shape:

```json
{
  "documents": {
    "Employer/project.md": {
      "status": "unverified",
      "employer": "Employer",
      "project": "Project name",
      "ownership": "Precisely what I contributed",
      "version": "2026-11-01-reviewed",
      "story_id": "project-name"
    }
  }
}
```

Review each file, its metrics and ownership before changing its status to `confirmed`.
Other statuses are `draft`, `synthetic` and `unverified`; none are retrieved by V2. Unlisted files
are also unverified. Use paths relative to the corpus, with forward slashes. Confirmed entries require
nonempty employer/project/ownership/version fields. If one file mixes real work and constructed
examples, split it first: file-level labels cannot separate individual claims.

```powershell
..\.venv\Scripts\python.exe -m copilot.cli ingest --version v2
..\.venv\Scripts\python.exe -m copilot.cli answer "Describe a pipeline failure you resolved" --version v2
..\.venv\Scripts\python.exe -m copilot.cli answer "What did I do on this project?" --version v2 --employer "Employer"
..\.venv\Scripts\python.exe -m streamlit run app.py
```

The UI defaults to V2. Choose V1 to use the original flow. V2's `auto` length/tone resolve to
medium/humanized without an extra model call. V2 does not use extra notes, fast mode or web search;
put factual notes in a reviewed document. Exit code 3 means V2 withheld the draft or requested more
evidence; exit code 2 means configuration is missing. Missing indexes require ingestion first.

When a source changes, update its manifest version and rerun V2 ingestion. The new snapshot becomes
active only after indexing succeeds. Old collections are retained locally but are not searched.
Changing the embedding model also requires ingestion. Avoid simultaneous ingests into one V2 path.

## 5. Keep and retest V1

```powershell
# Reuse an existing V1 index, or ingest once if you do not have one.
..\.venv\Scripts\python.exe -m copilot.cli answer "Describe a pipeline failure" --version v1 --fast
```

V1 uses `EXP_PERSIST_DIR` (default `chroma_store`); V2 uses `EXP_V2_PERSIST_DIR` (default
`chroma_store_v2`). V2 rejects overlapping paths. The untouched GitHub baseline is also preserved at
`baseline/experience-copilot-v1`; `main` is not changed by this development branch.

For real-corpus acceptance, keep a private list of interview questions with expected source files,
supported claims and expected abstentions. Ask the same question in both UI modes; inspect evidence,
employer, ownership, numbers and completeness. Record human judgments independently of the model's
own verification. The built-in comparison runner intentionally accepts fixture-source questions only;
it does not silently upload or benchmark your private corpus.
