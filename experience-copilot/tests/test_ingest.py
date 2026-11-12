"""Enricher labels and the incremental index over the example corpus."""
import json
import os
from pathlib import Path

from crag.ingest import BM25_FILE
from langchain_core.documents import Document

from copilot.ingest import build_index, enrich, experience_label, known_labels, strip_label
from eval.fakes import install


def test_label_from_top_folder():
    assert experience_label("Rocket/Rocket_KB_01.md") == "Rocket"


def test_label_maps_interview_subfolder_to_employer():
    assert experience_label("interview/Rocket/stories/ticket.md") == "Rocket"
    assert experience_label("interview/Rocket.md") == "Rocket"


def test_label_handles_windows_separators_and_root_files():
    assert experience_label("Contoso\\notes\\a.md") == "Contoso"
    assert experience_label("resume.md") == "resume"


def test_enrich_sets_metadata_and_prefix_once():
    doc = Document(page_content="Built a thing.", metadata={"source": "Northwind/a.md"})
    out = enrich(enrich(doc))
    assert out.metadata["experience"] == "Northwind"
    assert out.page_content == "[Experience: Northwind]\nBuilt a thing."
    assert strip_label(out.page_content) == "Built a thing."


def test_build_index_labels_every_chunk_and_is_incremental(settings):
    emb = install(lambda m, msgs, s: "x")
    first = build_index(settings)
    assert len(first.added_files) == 6 and first.chunks_embedded > 0
    records = json.loads((Path(settings.persist_dir) / BM25_FILE).read_text(encoding="utf-8"))
    assert {r["metadata"]["experience"] for r in records} == {"Northwind", "Contoso"}
    assert all(
        r["text"].startswith(f"[Experience: {r['metadata']['experience']}]") for r in records
    )
    before = emb.embedded
    second = build_index(settings)
    assert second.chunks_embedded == 0 and emb.embedded == before  # nothing re-embedded


def test_known_labels_from_corpus_and_index(indexed):
    assert known_labels(indexed) == {"Northwind", "Contoso"}


def test_ingest_does_not_mutate_environment(settings):
    install(lambda m, msgs, s: "x")
    before = dict(os.environ)
    build_index(settings)
    assert dict(os.environ) == before


def test_readme_and_dotfiles_are_not_ingested(make_settings, tmp_path):
    import pytest

    corpus = tmp_path / "corpus"
    (corpus / "Acme").mkdir(parents=True)
    (corpus / "README.md").write_text("# About this corpus\nNot experience.", encoding="utf-8")
    (corpus / "Acme" / "README.md").write_text("# Notes\nignore me", encoding="utf-8")
    (corpus / ".gitkeep").write_text("", encoding="utf-8")
    s = make_settings(corpus_dir=str(corpus))
    install(lambda m, msgs, sc: "x")
    with pytest.raises(ValueError):  # README-only corpus: zero ingestable files
        build_index(s)
    assert known_labels(s) == set()
    (corpus / "Acme" / "work.md").write_text("# Work\nBuilt things at Acme.", encoding="utf-8")
    report = build_index(s)
    assert report.added_files == ["Acme/work.md"]
    assert known_labels(s) == {"Acme"} and "README" not in known_labels(s, include_root_files=True)


def test_root_level_files_are_not_employer_labels(make_settings, tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "Acme").mkdir(parents=True)
    (corpus / "resume.md").write_text("# Resume\nData engineer.", encoding="utf-8")
    (corpus / "Acme" / "work.md").write_text("# Work\nBuilt things.", encoding="utf-8")
    s = make_settings(corpus_dir=str(corpus))
    install(lambda m, msgs, sc: "x")
    build_index(s)
    assert known_labels(s) == {"Acme"}
    assert known_labels(s, include_root_files=True) == {"Acme", "resume"}
