"""Idempotent incremental indexer: Chroma (dense) + a persisted BM25 corpus (`bm25.json`).

Why incremental: embedding is the slow, billable step. A manifest maps each source file to its
content hash and chunk ids, so a rerun with no changes makes zero embedding calls, an edited file
re-embeds only its own chunks, and a deleted file's chunks are removed from both stores.

Crash safety: the manifest is written last. If a run dies midway, the next run sees the file as
new/changed, deletes any of its chunk ids that landed, and adds them again.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from ..config import Settings, get_settings
from ..llm import get_embeddings
from .chunker import CHUNK_OVERLAP, CHUNK_SIZE, chunk_documents
from .loader import content_hash, load_documents

COLLECTION = "crag"
MANIFEST = "manifest.json"
BM25_FILE = "bm25.json"
_BATCH = 64

Enricher = Callable[[Document], Document]


@dataclass
class IndexReport:
    added_files: list[str]
    updated_files: list[str]
    removed_files: list[str]
    unchanged_files: list[str]
    chunks_embedded: int
    chunks_deleted: int


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def get_vectorstore(settings: Settings | None = None, embeddings: Any = None):
    """Open the persisted Chroma collection. Cosine space so `1 - distance` is a similarity."""
    import chromadb
    from langchain_chroma import Chroma

    s = settings or get_settings()
    return Chroma(
        collection_name=COLLECTION,
        persist_directory=s.persist_dir,
        embedding_function=embeddings or get_embeddings(),
        collection_metadata={"hnsw:space": "cosine"},
        client_settings=chromadb.config.Settings(
            anonymized_telemetry=False, is_persistent=True, persist_directory=s.persist_dir
        ),
    )


def index_ready(settings: Settings | None = None) -> bool:
    """Strict: manifest AND BM25 corpus both exist (a complete index; used by /readyz)."""
    d = Path((settings or get_settings()).persist_dir)
    return (d / MANIFEST).exists() and (d / BM25_FILE).exists()


def index_present(settings: Settings | None = None) -> bool:
    """Alias of `index_ready` (kept for existing callers)."""
    return index_ready(settings)


def index_retrievable(settings: Settings | None = None) -> bool:
    """Lenient: something retrievable exists (manifest, BM25 file, or a Chroma store).

    The retriever then degrades per store (BM25 missing -> dense only, Chroma missing -> BM25
    only) instead of the whole local path being skipped."""
    d = Path((settings or get_settings()).persist_dir)
    return any((d / n).exists() for n in (MANIFEST, BM25_FILE, "chroma.sqlite3"))


def build_index(
    settings: Settings | None = None,
    rebuild: bool = False,
    *,
    enricher: Enricher | None = None,
    embeddings: Any = None,
) -> IndexReport:
    """Bring the index in sync with `corpus_dir`.

    `enricher` may add metadata/labels to each chunk (the copilot prefixes employer labels). It is
    applied before embedding; changing an enricher does not change file hashes, so pass
    `rebuild=True` after changing one."""
    s = settings or get_settings()
    persist = Path(s.persist_dir)
    persist.mkdir(parents=True, exist_ok=True)

    docs = load_documents(s.corpus_dir)
    try:
        manifest = _read_json(persist / MANIFEST, {})
    except ValueError:  # corrupt manifest: treat as missing, rebuild from scratch
        manifest = {}
    if not isinstance(manifest, dict):
        manifest = {}
    if manifest and (
        manifest.get("embed_model") != s.embed_model  # vectors from another model: incomparable
        or manifest.get("chunk_size") != CHUNK_SIZE
        or manifest.get("chunk_overlap") != CHUNK_OVERLAP
        or not _intact(persist, s, embeddings, manifest)
    ):
        rebuild = True
    if rebuild or not manifest:
        manifest = {
            "embed_model": s.embed_model,
            "chunk_size": CHUNK_SIZE,
            "chunk_overlap": CHUNK_OVERLAP,
            "files": {},
        }
        _wipe_dense(persist, s, embeddings)
        bm25_records: list[dict[str, Any]] = []
    else:
        bm25_records = _read_json(persist / BM25_FILE, [])
    if not docs and not manifest["files"]:
        raise ValueError(f"No documents found in {s.corpus_dir}")

    files: dict[str, dict[str, Any]] = manifest["files"]
    current = {str(d.metadata["source"]): d for d in docs}
    hashes = {src: content_hash(d.page_content) for src, d in current.items()}

    removed = sorted(set(files) - set(current))
    added = sorted(set(current) - set(files))
    updated = sorted(src for src in current if src in files and files[src]["hash"] != hashes[src])
    unchanged = sorted(src for src in current if src in files and src not in updated)

    stale_ids = [cid for src in removed + updated for cid in files[src]["chunk_ids"]]
    new_chunks: list[Document] = []
    for src in added + updated:
        chunks = chunk_documents([current[src]], CHUNK_SIZE, CHUNK_OVERLAP)
        if enricher:
            chunks = [enricher(c) for c in chunks]
        new_chunks.extend(chunks)

    if stale_ids or new_chunks:
        store = get_vectorstore(s, embeddings)
        # Delete new ids too: makes a retry after a crash overwrite instead of duplicate.
        to_delete = list(dict.fromkeys(stale_ids + [c.metadata["chunk_id"] for c in new_chunks]))
        if to_delete:
            store.delete(ids=to_delete)
        for i in range(0, len(new_chunks), _BATCH):
            batch = new_chunks[i : i + _BATCH]
            store.add_documents(batch, ids=[c.metadata["chunk_id"] for c in batch])

    # Drop new ids too: a crash after the BM25 write but before the manifest write must not
    # leave duplicates when the same chunks are added again on the rerun.
    drop = set(stale_ids) | {c.metadata["chunk_id"] for c in new_chunks}
    bm25_records = [r for r in bm25_records if r["id"] not in drop]
    bm25_records += [
        {"id": c.metadata["chunk_id"], "text": c.page_content, "metadata": c.metadata}
        for c in new_chunks
    ]
    if not bm25_records:
        raise ValueError(f"No chunks produced from {s.corpus_dir}")
    changed = bool(stale_ids or new_chunks)
    if changed or not (persist / BM25_FILE).exists():
        _write_json(persist / BM25_FILE, bm25_records)

    for src in removed:
        del files[src]
    for src in added + updated:
        files[src] = {
            "hash": hashes[src],
            "chunk_ids": [
                c.metadata["chunk_id"] for c in new_chunks if c.metadata["source"] == src
            ],
        }
    _write_json(persist / MANIFEST, manifest)

    return IndexReport(
        added_files=added,
        updated_files=updated,
        removed_files=removed,
        unchanged_files=unchanged,
        chunks_embedded=len(new_chunks),
        chunks_deleted=len(stale_ids),
    )


def _intact(persist: Path, s: Settings, embeddings: Any, manifest: dict[str, Any]) -> bool:
    """True when BM25 and Chroma both still contain every chunk the manifest lists.

    Extras are tolerated (leftovers of a crashed run are replaced on rerun); anything missing
    means the stores drifted from the manifest, so the caller rebuilds."""
    expected = {cid for f in manifest.get("files", {}).values() for cid in f["chunk_ids"]}
    if not (persist / BM25_FILE).exists():
        return False
    try:
        bm25_ids = {r["id"] for r in _read_json(persist / BM25_FILE, [])}
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if not expected <= bm25_ids:
        return False
    if not expected:
        return True
    try:
        dense_ids = set(get_vectorstore(s, embeddings).get(include=[])["ids"])
    except Exception:
        return False
    return expected <= dense_ids


def _wipe_dense(persist: Path, s: Settings, embeddings: Any) -> None:
    """Drop any existing Chroma data so a rebuild starts clean. Never touches the corpus."""
    try:
        get_vectorstore(s, embeddings).delete_collection()
    except Exception:
        # Collection may not exist yet; fall back to clearing the directory contents.
        for child in persist.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
        (persist / "chroma.sqlite3").unlink(missing_ok=True)
    for name in (MANIFEST, BM25_FILE):
        (persist / name).unlink(missing_ok=True)
