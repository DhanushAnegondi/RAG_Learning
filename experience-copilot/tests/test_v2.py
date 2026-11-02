"""Offline behavioral tests; fake models never establish real answer quality."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from copilot import pipeline, retrieval_v2 as v2
from copilot.evaluation import isolated_indexes, load_questions, score


def passage(doc, text="I implemented Kafka deduplication.", key="chunk1", employer="Northstar"):
    return doc(text, chunk_id=key, parent_id=key, parent_text=text, source=f"{employer}/story.md",
               employer=employer, project="telemetry", evidence_status="confirmed",
               ownership="implemented deduplication", version="1", story_id="story", section=0)


def model(value):
    class Fake:
        def with_structured_output(self, schema):
            return self

        def invoke(self, messages):
            if isinstance(value, Exception):
                raise value
            return value
    return Fake()


def corpus(tmp_path):
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "story.md").write_text("# Story\nI implemented Kafka replay.\n## Result\nNo production metric was measured.", encoding="utf-8")
    return root


def write_manifest(root, **changes):
    entry = dict(status="confirmed", employer="Northstar", project="telemetry", ownership="implemented replay", version="1")
    entry.update(changes)
    (root / "evidence.json").write_text(json.dumps({"documents": {"story.md": entry}}), encoding="utf-8")


def test_unlisted_sources_remain_unverified(tmp_path):
    chunks = v2.prepare_chunks(str(corpus(tmp_path)))
    assert chunks and not v2.eligible(chunks)


def test_manifest_metadata_and_stable_ids(tmp_path):
    root = corpus(tmp_path)
    write_manifest(root)
    first = v2.prepare_chunks(str(root))
    assert len(first) == 2
    assert first[0].metadata["employer"] == "Northstar"
    assert first[0].metadata["ownership"] == "implemented replay"
    assert [d.metadata["chunk_id"] for d in first] == [d.metadata["chunk_id"] for d in v2.prepare_chunks(str(root))]
    write_manifest(root, version="2")
    assert first[0].metadata["chunk_id"] != v2.prepare_chunks(str(root))[0].metadata["chunk_id"]


@pytest.mark.parametrize("status", ["draft", "synthetic", "unverified"])
def test_nonconfirmed_sources_are_excluded(tmp_path, status):
    root = corpus(tmp_path)
    write_manifest(root, status=status)
    assert not v2.eligible(v2.prepare_chunks(str(root)))


@pytest.mark.parametrize("changes", [{"status": "verified-ish"}, {"ownership": ""}, {"version": None}])
def test_invalid_manifest_rejected(tmp_path, changes):
    root = corpus(tmp_path)
    write_manifest(root, **changes)
    with pytest.raises(ValueError):
        v2.prepare_chunks(str(root))


def test_manifest_path_escape_rejected(tmp_path):
    root = corpus(tmp_path)
    (root / "evidence.json").write_text(json.dumps({"documents": {"../outside.md": {"status": "draft"}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="inside corpus"):
        v2.prepare_chunks(str(root))


def test_employer_filter(doc):
    a, b = passage(doc), passage(doc, key="b", employer="Cedar")
    assert v2.eligible([a, b], "CEDAR") == [b]


def test_keyword_and_rrf_ranking(doc):
    a = passage(doc, "Kafka event_id deduplication", "a")
    b = passage(doc, "Snowflake loan_id reconciliation", "b")
    c = passage(doc, "Python validation", "c")
    assert v2.bm25("loan_id reconciliation", [a, b, c]) == [b]
    assert v2.bm25("", [a, b]) == []
    assert v2.fuse([[a, b], [b, c]])[0] == b


@pytest.mark.parametrize("value", [RuntimeError("down"), None,
    v2.EvidenceDecision(ranked_ids=["invented"], sufficient=True, missing=""),
    {"ranked_ids": "bad", "sufficient": True, "missing": ""}])
def test_grader_failure_never_becomes_coverage(monkeypatch, doc, value):
    monkeypatch.setattr(v2, "retrieve_candidates", lambda *a: [passage(doc)])
    monkeypatch.setattr(v2, "chat", lambda *a: model(value))
    result = v2.ground("What did I build?")
    assert not result["covered"] and result["error"] and not result["context"]


def test_topic_match_is_not_sufficient(monkeypatch, doc):
    monkeypatch.setattr(v2, "retrieve_candidates", lambda *a: [passage(doc)])
    monkeypatch.setattr(v2, "chat", lambda *a: model(v2.EvidenceDecision(
        ranked_ids=["chunk1"], sufficient=False, missing="What production throughput did you measure?")))
    result = v2.ground("What throughput did I achieve?")
    assert not result["covered"]
    assert "throughput" in result["missing"]


@pytest.mark.parametrize("quote,expected", [("implemented Kafka deduplication", True),
                                          ("invented throughput", False), ("", False)])
def test_recheck_requires_an_exact_evidence_quote(monkeypatch, doc, quote, expected):
    monkeypatch.setattr(v2, "retrieve_candidates", lambda *args: [passage(doc)])
    class Checker:
        def with_structured_output(self, schema):
            return model(v2.EvidenceDecision(ranked_ids=["chunk1"], sufficient=False, missing="more")
                         if schema is v2.EvidenceDecision else v2.EvidenceRecheck(sufficient=True, quote=quote))
    monkeypatch.setattr(v2, "chat", lambda *args: Checker())
    assert v2.ground("What was implemented?")["covered"] is expected


def test_recheck_sees_employer_and_reports_failure(monkeypatch, doc):
    monkeypatch.setattr(v2, "retrieve_candidates", lambda *args: [passage(doc)])
    class Checker:
        def with_structured_output(self, schema):
            if schema is v2.EvidenceDecision:
                return model(v2.EvidenceDecision(ranked_ids=["chunk1"], sufficient=False, missing="missing"))
            return self
        def invoke(self, messages):
            payload = json.loads(messages[1][1])
            assert payload["passages"][0]["employer"] == "Northstar"
            assert payload["passages"][0]["ownership"] == "implemented deduplication"
            raise RuntimeError("unavailable")
    monkeypatch.setattr(v2, "chat", lambda *args: Checker())
    result = v2.ground("What did Cedar build?")
    assert not result["covered"] and result["recheck_error"] == "RuntimeError"


def test_supported_context_has_sources_and_parent_dedup(monkeypatch, doc):
    a, b = passage(doc), passage(doc, key="chunk2")
    b.metadata["parent_id"] = a.metadata["parent_id"]
    monkeypatch.setattr(v2, "retrieve_candidates", lambda *args: [a, b])
    monkeypatch.setattr(v2, "chat", lambda *a: model(v2.EvidenceDecision(
        ranked_ids=["chunk1", "chunk2"], sufficient=True, missing="")))
    result = v2.ground("What did I build?")
    assert result["covered"] and len(result["sources"]) == 1
    assert "[S1] Employer: Northstar" in result["context"]


def test_no_coverage_does_not_call_generation(monkeypatch):
    monkeypatch.setattr(pipeline, "ground", lambda *a, **k: {"covered": False, "missing": "Confirm your role"})
    monkeypatch.setattr(pipeline, "generate_answer", lambda *a, **k: pytest.fail("must not generate"))
    assert pipeline.draft("q")["answer"] == "Confirm your role"


@pytest.mark.parametrize("answer", ["I built it.", "I built it [S9]."])
def test_bad_citations_block_the_draft(monkeypatch, answer):
    monkeypatch.setattr(pipeline, "ground", lambda *a, **k: {"covered": True, "context": "facts", "sources": [{"id": "S1"}]})
    monkeypatch.setattr(pipeline, "generate_answer", lambda *a, **k: answer)
    result = pipeline.draft("q")
    assert result["verified"] is False and result["answer"] != answer


@pytest.mark.parametrize("check", [pipeline.ClaimCheck(supported=False, reason="wrong employer"), RuntimeError("down")])
def test_claim_failure_blocks_the_draft(monkeypatch, check):
    monkeypatch.setattr(pipeline, "ground", lambda *a, **k: {"covered": True, "context": "facts", "sources": [{"id": "S1"}]})
    monkeypatch.setattr(pipeline, "generate_answer", lambda *a, **k: "I built it [S1].")
    monkeypatch.setattr(pipeline, "chat", lambda *a: model(check))
    result = pipeline.draft("q")
    assert result["verified"] is False and "I built it" not in result["answer"]


def test_checked_draft_passes(monkeypatch):
    monkeypatch.setattr(pipeline, "ground", lambda *a, **k: {"covered": True, "context": "facts", "sources": [{"id": "S1"}]})
    monkeypatch.setattr(pipeline, "generate_answer", lambda *a, **k: "I built it [S1].")
    monkeypatch.setattr(pipeline, "chat", lambda *a: model(pipeline.ClaimCheck(supported=True, reason="supported")))
    assert pipeline.draft("q")["verified"] is True


def test_indexes_must_be_separate(monkeypatch, tmp_path):
    monkeypatch.setenv("EXP_PERSIST_DIR", str(tmp_path / "v1"))
    monkeypatch.setenv("EXP_V2_PERSIST_DIR", str(tmp_path / "v1/child"))
    with pytest.raises(ValueError, match="separate"):
        v2.index_dir()


def test_relative_index_path_is_independent_of_working_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("EXP_V2_PERSIST_DIR", "chroma_store_v2")
    before = v2.index_dir()
    monkeypatch.chdir(tmp_path)
    assert v2.index_dir() == before


def test_long_section_keeps_both_selected_fragments(monkeypatch, tmp_path):
    root = corpus(tmp_path)
    (root / "story.md").write_text("# Long story\n" + "I implemented replay. " * 250 + "The result was zero duplicate rows.", encoding="utf-8")
    write_manifest(root)
    chunks = v2.prepare_chunks(str(root))
    chosen = [chunks[0], chunks[-1]]
    assert chosen[0].metadata["parent_id"] == chosen[1].metadata["parent_id"]
    monkeypatch.setattr(v2, "retrieve_candidates", lambda *args: chosen)
    monkeypatch.setattr(v2, "chat", lambda *args: model(v2.EvidenceDecision(
        ranked_ids=[d.metadata["chunk_id"] for d in chosen], sufficient=True, missing="")))
    result = v2.ground("What did I do and what was the result?")
    assert len(result["sources"]) == 2
    assert "zero duplicate rows" in result["context"]


def test_evaluation_environment_is_restored(monkeypatch, tmp_path):
    monkeypatch.setenv("EXP_CORPUS_DIR", "original")
    monkeypatch.delenv("CRAG_PERSIST_DIR", raising=False)
    with pytest.raises(RuntimeError):
        with isolated_indexes(tmp_path, tmp_path / "results"):
            monkeypatch.setenv("CRAG_PERSIST_DIR", "changed")
            raise RuntimeError("interrupt")
    import os
    assert os.environ["EXP_CORPUS_DIR"] == "original"
    assert "CRAG_PERSIST_DIR" not in os.environ


def test_evaluation_errors_are_not_correct_abstentions(tmp_path):
    row = dict(id="x", question="q", split="dev", answerable=False, expected_sources=[])
    scored = score(row, {"covered": False, "error": "NetworkError"}, tmp_path)
    assert scored["coverage_correct"] is False


def test_question_set_has_supported_and_unsupported_holdouts():
    path = Path(__file__).resolve().parents[1] / "eval/questions.jsonl"
    rows = load_questions(str(path))
    assert len(rows) == 48
    assert {r["answerable"] for r in rows if r["split"] == "holdout"} == {True, False}


def test_real_chroma_reindex_and_source_removal(monkeypatch, tmp_path):
    """Exercise actual persistence with tiny local embeddings, no NVIDIA calls."""
    from langchain_core.embeddings import Embeddings
    class LocalEmbeddings(Embeddings):
        def embed_documents(self, texts):
            return [self.embed_query(text) for text in texts]

        def embed_query(self, text):
            return [float(text.lower().count(term)) + .01 for term in ("kafka", "replay", "snowflake")]

    root = corpus(tmp_path)
    write_manifest(root)
    monkeypatch.setenv("EXP_V2_PERSIST_DIR", str(tmp_path / "index"))
    monkeypatch.setattr(v2, "get_embeddings", LocalEmbeddings)
    v2.build_index(str(root))
    before = json.loads((tmp_path / "index/index.json").read_text())
    v2.build_index(str(root))
    assert json.loads((tmp_path / "index/index.json").read_text())["collection"] == before["collection"]
    from langchain_chroma import Chroma
    store = Chroma(collection_name=before["collection"], persist_directory=str(tmp_path / "index"), embedding_function=LocalEmbeddings())
    assert len(store.get()["ids"]) == len(before["chunks"])
    assert v2.retrieve_candidates("Northstar Kafka replay")
    write_manifest(root, status="draft")
    v2.build_index(str(root))
    assert v2.retrieve_candidates("Northstar Kafka replay") == []
