# Ingestion and chunking

## Loading
- Normalize every file to documents carrying `source` (relative path). Read as UTF-8 explicitly.
- Reject or log unreadable files; never index a partial parse silently.

## Chunking
| Pattern | Use when | Failure mode / guard |
|---|---|---|
| Header-aware split, then recursive | Markdown or structured docs | Tiny chunks from short sections: merge below a minimum size |
| Recursive character split | Flat text | Splits mid-fact: add overlap (about 10-15%) |
| Fixed window | Quick baseline only | Cuts tables and lists: avoid for real corpora |

- Store `section` (header path) in metadata; it improves citations and exact-term matches.
- Chunk size is a tunable, not a fact. Change it only with a before/after eval on the same set.

## Idempotent incremental indexing
1. Manifest maps file path to content hash (sha256 of bytes).
2. On run: new or changed file, re-chunk and embed; removed or changed file, delete its old chunks; unchanged, skip.
3. `chunk_id = sha256(source + section + ordinal + content)`; upserts are safe to repeat.
4. Dense store and BM25 corpus are updated together; persist the BM25 corpus (ids, text, metadata) so restarts do not re-read sources.
5. Verify: no-change rerun = zero embedding calls; edit one file = only that file re-embedded; delete a file = its chunks gone.
6. A changed embedding model or chunker version invalidates the manifest: rebuild, do not mix vectors.

## Failure modes
- Duplicate chunks after re-ingest (non-deterministic ids).
- Stale chunks of deleted files still retrievable.
- Index built with one embedding model, queried with another.
