"""Grounding: coverage in fast and graded mode, fail-open grading, no env mutation."""
import os

import pytest
from crag.nodes.grade import GradeDecision
from crag.retrieval import ScoredChunk

from copilot.engine import (
    assess_coverage,
    content_terms,
    ground,
    lexical_hits,
    named_entities,
)
from eval.fakes import install


def _chunk(text, cid="c1"):
    return ScoredChunk(chunk_id=cid, text=text, metadata={"experience": "X"})


def test_content_terms_drop_boilerplate_and_stem():
    assert content_terms("Tell me about your experience with migrations") == {"migration"}
    assert content_terms("migration") == content_terms("migrations")
    assert content_terms("reduce") == content_terms("reducing")
    assert content_terms("the data pipeline project design") == set()  # all generic


def test_lexical_ignores_label_prefix():
    c = _chunk("[Experience: Contoso]\nWe built dashboards.")
    assert lexical_hits("What did you do at Contoso with dashboards?", c.text) == 1  # not 2


def _cov(question, chunks, dense=None, hits=2, thr=0.9):
    return assess_coverage(
        question, chunks, dense or {}, lexical_min_hits=hits, dense_threshold=thr
    )


def test_assess_coverage_rules():
    chunks = [_chunk("We migrated the warehouse to a lakehouse.")]
    ok, why = _cov("warehouse lakehouse migration", chunks)
    assert ok and "lexical" in why
    assert not _cov("quantum chemistry hobby", chunks)[0]
    # dense alone never marks covered, however high; it may only veto a lexical match
    assert not _cov("quantum chemistry hobby", chunks, {"c1": 0.99}, thr=0.1)[0]
    assert _cov("warehouse lakehouse", chunks, {"c1": 0.5}, thr=0.3)[0]
    assert not _cov("warehouse lakehouse", chunks, {"c1": 0.1}, thr=0.3)[0]
    assert _cov("anything", [], thr=0.1) == (False, "nothing retrieved")


def test_single_specific_term_question_needs_one_hit():
    assert _cov("kafka streams?", [_chunk("We ran Kafka streams.")])[0]
    assert _cov("kafka?", [_chunk("We ran Kafka streams.")])[0]


def test_fast_mode_covered_without_any_llm_call(indexed):
    calls = []
    install(lambda m, msgs, s: calls.append(m) or "boom")
    g = ground("How did you reduce cloud costs at Contoso?", grade=False, settings=indexed)
    assert calls == []  # no grading call
    assert g.covered and not g.graded and "Contoso" in g.labels
    assert "<doc" in g.context and not g.errors


def test_fast_mode_flags_uncovered_question(indexed):
    """The v0 bug: the default (fast) path never flagged thin coverage."""
    for q in ("What did you accomplish at Fabrikam?", "Tell me about Kubernetes operators."):
        g = ground(q, grade=False, settings=indexed)
        assert not g.covered, q
        assert not g.graded


def test_realistic_dense_threshold_keeps_in_kb_covered_and_never_creates_coverage(
    make_settings, indexed
):
    s = make_settings(persist_dir=indexed.persist_dir, dense_threshold=0.3)
    install(lambda m, msgs, sc: "x")
    hit = ground("How did you reduce cloud costs at Contoso?", grade=False, settings=s)
    assert hit.covered and "anchored on Contoso" in hit.reason
    assert not ground("quantum chemistry hobby", grade=False, settings=s).covered
    strict = make_settings(persist_dir=indexed.persist_dir, dense_threshold=0.99)
    vetoed = ground("How did you reduce cloud costs at Contoso?", grade=False, settings=strict)
    assert not vetoed.covered and "weak match" in vetoed.reason


def test_entity_aware_false_positives_are_uncovered(indexed):
    for q in (
        "Tell me about the data pipeline you built at Fabrikam",
        "How did you design the pipeline architecture at Acme?",
    ):
        g = ground(q, grade=False, settings=indexed)
        assert not g.covered and "isn't in your documents" in g.reason, q
    assert "Fabrikam" in ground(
        "Tell me about the data pipeline you built at Fabrikam", grade=False, settings=indexed
    ).reason


def test_generic_only_question_is_uncovered(indexed):
    g = ground("Describe a data project", grade=False, settings=indexed)
    assert not g.covered and "generic" in g.reason


def test_in_kb_named_question_stays_covered(indexed):
    g = ground("What billing pipeline did you build at Northwind?", grade=False, settings=indexed)
    assert g.covered and g.labels[0] == "Northwind"
    assert named_entities("What billing pipeline did you build at Northwind?") == ["Northwind"]
    assert named_entities("Describe a data project") == []


def test_graded_mode_also_applies_entity_check(indexed, client_for):
    install(lambda m, msgs, s: GradeDecision(relevant=True))
    g = ground(
        "Tell me about the data pipeline you built at Fabrikam",
        grade=True, settings=indexed, client=client_for(indexed),
    )
    assert g.n_relevant > 0 and not g.covered


def _grader(keep_word):
    def handler(model, messages, schema):
        text = messages[-1][1] if isinstance(messages[-1], tuple) else str(messages)
        return GradeDecision(relevant=keep_word in text)

    return handler


def test_graded_mode_filters_and_uses_grader_model(indexed, client_for):
    seen = []

    def handler(model, messages, schema):
        seen.append(model)
        return _grader("Terraform")(model, messages, schema)

    install(handler)
    g = ground(
        "lakehouse migration at Contoso", grade=True, settings=indexed, client=client_for(indexed)
    )
    assert g.graded and seen and set(seen) == {indexed.grader_model}
    assert all("Terraform" in c.text for c in g.kept) and g.n_relevant == len(g.kept) >= 1
    assert g.covered


def test_graded_uncovered_when_no_chunk_relevant(indexed, client_for):
    install(_grader("zzz-never"))
    g = ground(
        "lakehouse migration at Contoso", grade=True, settings=indexed, client=client_for(indexed)
    )
    assert g.n_relevant == 0 and not g.covered and g.context == ""


def test_grader_failure_is_fail_open_and_falls_back_to_fast_rule(indexed, client_for):
    install(lambda m, msgs, s: RuntimeError("grader down"))
    hit = ground(
        "lakehouse migration at Contoso", grade=True, settings=indexed, client=client_for(indexed)
    )
    assert hit.kept and hit.covered and hit.degraded
    assert "fell back" in hit.reason
    miss = ground(
        "What did you accomplish at Fabrikam?",
        grade=True,
        settings=indexed,
        client=client_for(indexed),
    )
    assert miss.kept and not miss.covered  # fail-open kept chunks; the fast rule still says no


def test_missing_index_degrades_instead_of_raising(settings):
    install(lambda m, msgs, s: "x")
    g = ground("anything about billing", grade=False, settings=settings)
    assert g.degraded and not g.covered and g.kept == [] and g.errors


def test_pipeline_does_not_mutate_environment(settings, client_for):
    """build_index, ground (fast + graded) and generate_answer leave os.environ untouched."""
    from copilot.answer import generate_answer
    from copilot.ingest import build_index

    install(lambda m, msgs, s: GradeDecision(relevant=True) if s else "At Contoso I did it.")
    before = dict(os.environ)
    build_index(settings)
    ground("lakehouse migration", grade=False, settings=settings)
    g = ground("lakehouse migration", grade=True, settings=settings, client=client_for(settings))
    generate_answer("lakehouse migration", g, settings=settings, client=client_for(settings))
    assert dict(os.environ) == before


def test_question_naming_the_chunks_employer_needs_one_specific_hit():
    c = ScoredChunk(
        chunk_id="c1", text="[Experience: Northwind]\nWe improved quality checks.",
        metadata={"experience": "Northwind"},
    )
    ok, _ = assess_coverage(
        "How did you boost reliability and quality at Northwind?", [c], {},
        lexical_min_hits=2, dense_threshold=0.0, known={"Northwind"},
    )
    assert ok
    ok, _ = assess_coverage(
        "How did you boost reliability and quality?", [c], {},
        lexical_min_hits=2, dense_threshold=0.0, known={"Northwind"},
    )
    assert not ok  # same hits, but not anchored to an employer


COVERED = [
    "What billing pipeline did you build at Northwind?",
    "What did you build at Northwind?",
    "Northwind: what did you ship?",
    "How do you handle data quality?",
    "Tell me about a data quality problem you solved",
    "How did you mentor engineers?",
    "How did you use Kafka?",
    "What did you do with Spark?",
    "What billing pipeline are you most proud of?",
]
NOT_COVERED = [
    "Tell me about the data pipeline you built at Fabrikam.",
    "How did you design the pipeline architecture at Acme?",
    "Describe a data project",
    "What did you do with SQL Server at Initech?",
    "What data pipeline are you most proud of?",  # no specific term: documented as not covered
]


def _table_handler(model, messages, schema):
    """Grader stand-in: relevant when it shares a specific term or names the chunk's employer."""
    import re

    text = messages[-1][1]
    q = re.search(r"Question: (.*)", text).group(1)
    doc = re.search(r"<doc>\n(.*?)\n</doc>", text, re.S).group(1)
    label = re.search(r"\[Experience: ([^\]]+)\]", doc).group(1)
    return GradeDecision(relevant=lexical_hits(q, doc) >= 1 or label.lower() in q.lower())


@pytest.mark.parametrize("grade", [False, True], ids=["fast", "graded"])
@pytest.mark.parametrize(
    "question,expected",
    [(q, True) for q in COVERED] + [(q, False) for q in NOT_COVERED],
)
def test_coverage_table(indexed, client_for, question, expected, grade):
    install(_table_handler)
    g = ground(question, grade=grade, settings=indexed, client=client_for(indexed))
    assert g.covered is expected, (question, g.reason)


def test_verbatim_phrase_counts_as_one_hit():
    chunk = _chunk("Our data quality program added tests.")
    # "data" and "quality" are matched as one phrase, replacing the single-word hit for "quality"
    ok, why = assess_coverage(
        "How do you handle data quality?", [chunk], {}, lexical_min_hits=2, dense_threshold=0.0
    )
    assert ok and "1 hit" in why
    ok, _ = assess_coverage(
        "data pipeline?", [_chunk("A data pipeline ran nightly.")], {},
        lexical_min_hits=2, dense_threshold=0.0,
    )
    assert ok  # no specific term, but the generic phrase appears verbatim
    ok, _ = assess_coverage(
        "data project?", [_chunk("A data pipeline ran nightly.")], {},
        lexical_min_hits=2, dense_threshold=0.0,
    )
    assert not ok


def test_named_entities_sentence_start_rules():
    assert named_entities("Northwind: what did you ship?", {"Northwind"}) == ["Northwind"]
    assert named_entities("Fabrikam: what did you ship?") == ["Fabrikam"]
    assert named_entities("What did you do with SQL Server at Initech?") == [
        "SQL", "Server", "Initech"
    ]
    assert named_entities("Describe a data project") == []
