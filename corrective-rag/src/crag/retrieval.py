"""Retriever: dense (Chroma), BM25, or hybrid via Reciprocal Rank Fusion, with graceful degradation.

Why hybrid: dense embeddings are strong on paraphrase but blur exact identifiers (`FEE-NSF-02`);
BM25 is the opposite. RRF fuses *ranks*, not scores, so the incompatible score scales never need
calibrating. If the embeddings API is down we still answer from BM25 and flag `degraded`.
"""

from __future__ import annotations

import logging
import math
import re
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from rank_bm25 import BM25Okapi

from .config import Settings, get_settings
from .observability import current_context

log = logging.getLogger("crag.retrieval")

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens: `FEE-NSF-02` -> fee, nsf, 02."""
    return _TOKEN_RE.findall(text.lower())


class _BM25(BM25Okapi):
    """BM25Okapi with Lucene-style IDF, log(1 + (N - n + 0.5) / (n + 0.5)).

    The stock IDF is 0 (or negative, then floored) for terms present in half or more of the
    docs, so on tiny corpora a matching doc can score 0 and look like a miss."""

    def _calc_idf(self, nd: dict[str, int]) -> None:
        total = 0.0
        for word, freq in nd.items():
            self.idf[word] = math.log(1.0 + (self.corpus_size - freq + 0.5) / (freq + 0.5))
            total += self.idf[word]
        self.average_idf = total / len(nd) if nd else 0.0


class ScoredChunk(BaseModel):
    chunk_id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0
    ranks: dict[str, int] = Field(default_factory=dict)  # retriever name -> 1-based rank


def rrf_fuse(rankings: dict[str, list[str]], k: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion: score(d) = sum over retrievers of 1 / (k + rank_r(d))."""
    scores: dict[str, float] = {}
    for ids in rankings.values():
        for rank, cid in enumerate(ids, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return scores


class Retriever:
    def __init__(self, settings: Settings | None = None, *, vectorstore: Any = None):
        self.settings = settings or get_settings()
        self._store = vectorstore
        self._store_injected = vectorstore is not None
        self._store_manifest_mtime: float | None = None
        # (records, model, mtime) published as ONE tuple so a search never pairs scores from one
        # corpus with records from another.
        self._bm25_snapshot: tuple[list[dict[str, Any]], BM25Okapi, float] | None = None
        self._bm25_lock = threading.Lock()

    # -- public -------------------------------------------------------------------------------

    def retrieve(self, query: str, k: int | None = None) -> list[ScoredChunk]:
        k = k or self.settings.top_k
        fetch_k = max(self.settings.fetch_k, k)
        mode = self.settings.retrieval_mode
        dense: list[ScoredChunk] | None = None
        sparse: list[ScoredChunk] | None = None
        if mode != "bm25":
            dense = self._try("dense", lambda: self._dense(query, fetch_k))
        if mode != "dense":
            sparse = self._try("bm25", lambda: self._bm25_search(query, fetch_k))
        if dense is None and sparse is None:
            # The requested retriever failed outright: try the other one before giving up.
            if mode == "dense":
                sparse = self._try("bm25", lambda: self._bm25_search(query, fetch_k))
            elif mode == "bm25":
                dense = self._try("dense", lambda: self._dense(query, fetch_k))
        if dense is None and sparse is None:
            self._degraded("retrieval unavailable: no usable index")
            return []
        missing_requested = (mode != "bm25" and dense is None) or (
            mode != "dense" and sparse is None
        )
        if missing_requested:
            self._degraded(f"retrieval degraded: {'bm25' if dense is None else 'dense'} only")
        if dense is not None and sparse is not None:
            return self._fuse(dense, sparse, k)
        return _dedupe(dense if dense is not None else sparse or [])[:k]

    # -- retrievers ---------------------------------------------------------------------------

    def _try(self, name: str, fn: Any) -> list[ScoredChunk] | None:
        try:
            return fn()
        except Exception as exc:  # any provider/index failure degrades rather than raises
            log.warning("%s retrieval failed: %s", name, type(exc).__name__)
            ctx = current_context()
            if ctx is not None:
                ctx.record_error(f"{name} retrieval failed: {type(exc).__name__}: {exc}")
            return None

    def _degraded(self, reason: str) -> None:
        ctx = current_context()
        if ctx is not None:
            ctx.mark_degraded(reason)

    def _manifest_mtime(self) -> float | None:
        try:
            return (Path(self.settings.persist_dir) / "manifest.json").stat().st_mtime
        except OSError:
            return None

    def _vectorstore(self) -> Any:
        """The Chroma handle, reopened when the index was rebuilt under us.

        `build_index(rebuild=True)` drops and recreates the collection (new UUID), which leaves a
        long-lived handle pointing at a collection that no longer exists. The manifest is written
        last by every index run, so its mtime changing means 'reopen'."""
        if self._store_injected:
            return self._store
        mtime = self._manifest_mtime()
        if self._store is None or mtime != self._store_manifest_mtime:
            from .ingest.indexer import get_vectorstore

            self._store = get_vectorstore(self.settings)
            self._store_manifest_mtime = mtime
        return self._store

    def _dense(self, query: str, fetch_k: int) -> list[ScoredChunk]:
        try:
            pairs = self._vectorstore().similarity_search_with_score(query, k=fetch_k)
        except Exception as exc:
            if self._store_injected or not _is_missing_collection(exc):
                raise
            self._store = None  # stale handle (collection recreated): reopen and retry once
            pairs = self._vectorstore().similarity_search_with_score(query, k=fetch_k)
        out: list[ScoredChunk] = []
        for rank, (doc, dist) in enumerate(pairs, start=1):
            cid = doc.metadata.get("chunk_id") or f"dense-{rank}"
            out.append(
                ScoredChunk(
                    chunk_id=cid,
                    text=doc.page_content,
                    metadata=dict(doc.metadata),
                    score=1.0 - float(dist),  # cosine collection: distance = 1 - similarity
                    ranks={"dense": rank},
                )
            )
        return out

    def _load_bm25(self) -> tuple[list[dict[str, Any]], BM25Okapi]:
        """Return one consistent (records, model) snapshot, reloading if bm25.json changed."""
        path = Path(self.settings.persist_dir) / "bm25.json"
        mtime = path.stat().st_mtime  # FileNotFoundError => BM25 missing => caller degrades
        snap = self._bm25_snapshot
        if snap is None or snap[2] != mtime:
            import json

            records = json.loads(path.read_text(encoding="utf-8"))
            if not records:
                raise ValueError("bm25 corpus is empty")
            model = _BM25([tokenize(r["text"]) for r in records])
            with self._bm25_lock:
                self._bm25_snapshot = snap = (records, model, mtime)
        return snap[0], snap[1]

    def _bm25_search(self, query: str, fetch_k: int) -> list[ScoredChunk]:
        records, bm25 = self._load_bm25()  # one snapshot for the whole search
        scores = bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        out: list[ScoredChunk] = []
        for i in order[:fetch_k]:
            if scores[i] <= 0:
                break  # no query term matched: not a hit
            r = records[i]
            out.append(
                ScoredChunk(
                    chunk_id=r["id"],
                    text=r["text"],
                    metadata=r["metadata"],
                    score=float(scores[i]),
                    ranks={"bm25": len(out) + 1},
                )
            )
        return out

    def _fuse(
        self, dense: list[ScoredChunk], sparse: list[ScoredChunk], k: int
    ) -> list[ScoredChunk]:
        dense, sparse = _dedupe(dense), _dedupe(sparse)
        scores = rrf_fuse(
            {
                "dense": [c.chunk_id for c in dense],
                "bm25": [c.chunk_id for c in sparse],
            },
            self.settings.rrf_k,
        )
        merged: dict[str, ScoredChunk] = {}
        for c in [*dense, *sparse]:
            if c.chunk_id in merged:
                merged[c.chunk_id].ranks.update(c.ranks)
            else:
                merged[c.chunk_id] = c.model_copy(update={"ranks": dict(c.ranks)})
        for cid, c in merged.items():
            c.score = scores[cid]
        return sorted(merged.values(), key=lambda c: c.score, reverse=True)[:k]


def _is_missing_collection(exc: BaseException) -> bool:
    """chromadb raises NotFoundError ('Collection ... does not exist') on a recreated collection."""
    return type(exc).__name__ == "NotFoundError" or "does not exist" in str(exc).lower()


def _dedupe(chunks: list[ScoredChunk]) -> list[ScoredChunk]:
    seen: set[str] = set()
    out: list[ScoredChunk] = []
    for c in chunks:
        if c.chunk_id not in seen:
            seen.add(c.chunk_id)
            out.append(c)
    return out
