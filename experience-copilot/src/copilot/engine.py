"""Grounding engine: hybrid retrieval, optional parallel grading, and a coverage decision.

Coverage ("do the documents actually cover this question?") must work WITHOUT grading, because
the UI default is fast mode. v0 only judged coverage when graded, so the default path never
warned about thin coverage.

Coverage rules
--------------
Fast mode (no LLM call). Rules apply in this order; the first that fires decides:
  a. Unknown entity. A capitalised word that is neither a sentence opener nor a known label
     ("... at Fabrikam", "with SQL Server") must appear in some retrieved chunk body; otherwise NOT
     covered, "names X, which isn't in your documents". A sentence-initial word counts as an entity
     only when followed by ':' or when it is a known label; common question words (What, How,
     Tell, ...) are never entities.
  b. Anchored. The question names a known label (e.g. "at Northwind") and a retrieved chunk carries
     that label: covered, "anchored on <label>".
  c. Entity found. The question names an entity (Kafka, Spark) that appears in a retrieved chunk:
     covered. (Rule a already rejected entities that appear nowhere.)
  d. Lexical. Specific terms = content words minus stopwords, generic domain nouns (data, pipeline,
     project, ...) and interview filler (handle, solve, problem, proud, ship, ...). A chunk covers
     the question when it shares >= min(lexical_min_hits, n) specific terms, n being the number of
     specific terms. Adjacent question word pairs found verbatim in the chunk ("data quality")
     count as ONE hit when none of their words matched as a specific term (so a purely generic
     phrase counts, and 'data quality' is not double counted).
     No specific terms and no verbatim phrase hit: never covered.
  Dense veto (applies to b, c and d): when dense scores exist, the SAME chunk must also reach
  `dense_threshold`. Dense similarity never creates coverage by itself; the threshold is not
  calibrated against the live embedder. If the dense retriever was unavailable, lexical rules
  decide.
Graded mode: covered when at least `coverage_threshold` chunks are judged relevant AND rule a
passes.
If grading failed (the grader is fail-open, so every chunk is kept on error), the verdict falls
back to the fast rule instead of trusting the fail-open "all relevant".

Limits: surface overlap misses paraphrase; entity detection is capitalisation-based; an anchored
question ("What is your hobby at Northwind?") is covered even if the topic is not, unless the topic
is a capitalised entity. eval/ measures coverage-detection accuracy for both modes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from crag.guardrails import format_context, validate_question
from crag.llm import LLMClient
from crag.nodes.grade import grade_texts
from crag.observability import run_context
from crag.retrieval import Retriever, ScoredChunk, tokenize
from langchain_core.documents import Document

from .config import Settings, get_settings
from .ingest import experience_label, known_labels, strip_label

# Words that carry no evidence of coverage: function words plus interview boilerplate.
_STOP = frozenset(
    """
    a an and are as at be been being but by can could did do does doing done for from
    had has have having how i if in into is it its me my of on or our so than that the
    their them then there these they this those to was we were what when where which
    while who whom why will with would you your about also any all both each few get got
    give gave just like made make more most much no not now one only other out over own
    same she he some such too up very yourself tell talk describe explain walk through
    experience experiences work worked working project projects role roles company
    companies example examples time times thing things
    """.split()
)


def _stem(tok: str) -> str:
    """Crude stemmer: drops -ing/-ed, plural -s/-ies and a trailing -e, so pipeline/pipelines and
    reduce/reducing meet. Over-stemming is harmless here: both sides use the same function."""
    for suf in ("ing", "ed"):
        if tok.endswith(suf) and len(tok) - len(suf) >= 4:
            tok = tok[: -len(suf)]
            break
    else:
        if tok.endswith("ies") and len(tok) > 4:
            tok = tok[:-3] + "y"
        elif tok.endswith("s") and not tok.endswith("ss") and len(tok) > 3:
            tok = tok[:-1]
    return tok[:-1] if tok.endswith("e") and len(tok) > 4 else tok


# Domain nouns present in nearly every data-engineering document: no evidence of coverage.
_GENERIC = frozenset(
    """data pipeline pipelines project system systems design architecture team teams built build
    building tool tools platform process processes solution solutions""".split()
)
# Interview filler: words of the question frame, not of the topic.
_FILLER = frozenset(
    """handle solve solved problem problems check checks improve improved proud ship shipped
    deliver delivered approach work worked experience tell describe example time favorite
    favourite challenge challenging most""".split()
)
_QUESTION_WORDS = frozenset(
    """what how tell describe why when which who whom where can could did do does have has had is
    are was were would should will walk give explain compare share talk name list show summarize
    please i""".split()
)


def _stem_set(words: frozenset[str]) -> frozenset[str]:
    return frozenset(_stem(w) for w in words) | words


_NOT_SPECIFIC = _stem_set(_GENERIC | _FILLER)


def content_terms(text: str) -> set[str]:
    """Distinct stemmed SPECIFIC words (no stopwords, generic nouns, filler or short tokens)."""
    out = set()
    for t in tokenize(text):
        if len(t) > 2 and t not in _STOP and t not in _NOT_SPECIFIC:
            st = _stem(t)
            if st not in _NOT_SPECIFIC:
                out.add(st)
    return out


def lexical_hits(question: str, chunk_text: str, ignore: set[str] | None = None) -> int:
    """How many distinct specific terms of the question appear in the chunk body.

    `ignore` holds stemmed terms to skip (known labels: the anchor/entity rules cover those)."""
    q = content_terms(question) - (ignore or set())
    return len(q & content_terms(strip_label(chunk_text)))


def _bigrams(question: str) -> list[tuple[str, str]]:
    toks = [t for t in tokenize(question)]
    return [
        (a, b)
        for a, b in zip(toks, toks[1:], strict=False)
        if len(a) > 2 and len(b) > 2 and a not in _STOP and b not in _STOP
    ]


def _chunk_hits(question: str, body: str, label_terms: set[str]) -> int:
    """Specific-term hits plus verbatim two-word phrase hits.

    A phrase adds a hit only when none of its words already matched as a specific term, so
    "data quality" (quality matched) is not double counted but a purely generic phrase such as
    "data pipeline" still counts once."""
    matched = (content_terms(question) - label_terms) & content_terms(body)
    padded = " " + " ".join(tokenize(body)) + " "
    phrases = [bg for bg in _bigrams(question) if f" {bg[0]} {bg[1]} " in padded]
    extra = [bg for bg in phrases if not ({_stem(w) for w in bg} & matched)]
    return len(matched) + len(extra)


_CAP_RE = re.compile(r"\b[A-Z][\w&-]*")


def named_entities(question: str, known: set[str] | None = None) -> list[str]:
    """Capitalised words naming an organisation/tool ("... at Fabrikam", "with Kafka").

    A sentence-initial word counts only when followed by ':' or when it is a known label, and
    never when it is a common question word."""
    labels = {k.lower() for k in (known or set())}
    out: list[str] = []
    for m in _CAP_RE.finditer(question):
        word = m.group(0)
        before = question[: m.start()].rstrip()
        if len(word) < 2:
            continue
        if not before or before[-1] in ".?!:;":  # sentence start
            if word.lower() in _QUESTION_WORDS:
                continue
            if not (question[m.end() : m.end() + 1] == ":" or word.lower() in labels):
                continue
        if word.lower() not in (e.lower() for e in out):
            out.append(word)
    return out


def _body_tokens(chunk: ScoredChunk) -> set[str]:
    return set(tokenize(strip_label(chunk.text)))


def missing_entities(
    question: str, chunks: list[ScoredChunk], known: set[str]
) -> list[str]:
    """Entities the question names that are neither a known label nor in any retrieved chunk."""
    labels = {k.lower() for k in known}
    body: set[str] = set()
    for c in chunks:
        body |= _body_tokens(c)
    return [
        e
        for e in named_entities(question, known)
        if e.lower() not in labels and not set(tokenize(e)) <= body
    ]


def _names_label(question: str, label: str) -> bool:
    return bool(re.search(rf"\b{re.escape(label)}\b", question, re.I))


def assess_coverage(
    question: str,
    chunks: list[ScoredChunk],
    dense_scores: dict[str, float],
    *,
    lexical_min_hits: int,
    dense_threshold: float,
    known: set[str] | None = None,
) -> tuple[bool, str]:
    """The fast-mode coverage rule (pure); see the module docstring. Returns (covered, reason)."""
    known = known or set()
    if not chunks:
        return False, "nothing retrieved"
    missing = missing_entities(question, chunks, known)
    if missing:  # rule a
        return False, f"names {', '.join(missing)}, which isn't in your documents"

    dense_available = any(c.chunk_id in dense_scores for c in chunks)

    def sim_ok(c: ScoredChunk) -> bool:
        return not dense_available or dense_scores.get(c.chunk_id, 0.0) >= dense_threshold

    named = [k for k in sorted(known) if _names_label(question, k)]  # rule b
    for c in chunks:
        if sim_ok(c) and chunk_label(c).lower() in {n.lower() for n in named}:
            return True, f"anchored on {chunk_label(c)}"

    labels = {k.lower() for k in known}  # rule c
    entities = [e for e in named_entities(question, known) if e.lower() not in labels]
    for c in chunks:
        if sim_ok(c):
            found = [e for e in entities if set(tokenize(e)) <= _body_tokens(c)]
            if found:
                return True, f"names {found[0]}, found in your documents"

    label_terms = set().union(*(content_terms(k) for k in known)) if known else set()  # rule d
    q_terms = content_terms(question) - label_terms
    need = min(lexical_min_hits, len(q_terms)) if q_terms else 1
    best_hits, best_dense = 0, 0.0
    for c in chunks:
        hits = _chunk_hits(question, strip_label(c.text), label_terms)
        best_hits = max(best_hits, hits)
        sim = dense_scores.get(c.chunk_id, 0.0)
        best_dense = max(best_dense, sim)
        if hits >= max(need, 1) and sim_ok(c):
            how = f"lexical {hits} hit(s) for {len(q_terms)} specific term(s)"
            if dense_available:
                how += f" + dense similarity {sim:.2f} >= {dense_threshold:.2f}"
            return True, how
    if not q_terms and best_hits == 0:
        return False, "only generic terms in the question; nothing specific to match"
    return False, (
        f"weak match: best lexical {best_hits}/{max(need, 1)}, best similarity {best_dense:.2f}"
    )


class SignalRetriever(Retriever):
    """crag `Retriever` that also remembers each chunk's raw dense cosine similarity.

    Hybrid fusion replaces scores with RRF values, which say nothing about absolute relevance, so
    coverage needs the raw dense score. This overrides crag's protected `_dense` hook (a coupling
    to crag internals, covered by tests). One instance per call: the dict is per-retrieval state."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.dense_scores: dict[str, float] = {}

    def retrieve(self, query: str, k: int | None = None) -> list[ScoredChunk]:
        self.dense_scores = {}
        return super().retrieve(query, k)

    def _dense(self, query: str, fetch_k: int) -> list[ScoredChunk]:
        out = super()._dense(query, fetch_k)
        self.dense_scores = {c.chunk_id: c.score for c in out}
        return out


@dataclass
class Grounding:
    """What the answer step needs, plus what the UI needs to explain it."""

    context: str  # <doc>-wrapped kept chunks (untrusted data); "" when nothing was kept
    kept: list[ScoredChunk]
    labels: list[str]  # experience labels of the kept chunks, first-seen order
    n_relevant: int
    covered: bool
    graded: bool
    degraded: bool
    errors: list[str] = field(default_factory=list)
    reason: str = ""  # why covered / not covered


def chunk_label(chunk: ScoredChunk) -> str:
    return str(
        chunk.metadata.get("experience")
        or experience_label(str(chunk.metadata.get("source", "")))
    )


def ground(
    question: str,
    *,
    grade: bool = True,
    settings: Settings | None = None,
    client: LLMClient | None = None,
    retriever: Retriever | None = None,
) -> Grounding:
    """Retrieve (hybrid), optionally grade in parallel with the grader model, decide coverage.

    Never raises on provider/index faults: they degrade and are reported in `errors`. Raises
    ValueError only for an empty/oversized question."""
    s = settings or get_settings()
    cs = s.to_crag_settings()
    q = validate_question(question, cs.max_question_chars)
    labels_known = known_labels(s)
    with run_context() as ctx:
        retriever = retriever or SignalRetriever(cs)
        try:
            chunks = retriever.retrieve(q, s.top_k)
        except Exception as exc:  # defensive: Retriever already degrades on its own faults
            ctx.record_error(f"retrieval failed: {type(exc).__name__}: {exc}")
            ctx.mark_degraded()
            chunks = []
        dense = dict(getattr(retriever, "dense_scores", {}))
        fast_ok, fast_reason = assess_coverage(
            q,
            chunks,
            dense,
            lexical_min_hits=s.lexical_min_hits,
            dense_threshold=s.dense_threshold,
            known=labels_known,
        )

        if not grade:
            kept, covered, reason, n_rel = chunks, fast_ok, fast_reason, len(chunks)
        else:
            grades = grade_texts(q, [c.text for c in chunks], client or LLMClient(cs), cs)
            kept = [c for c, g in zip(chunks, grades, strict=True) if g]
            n_rel = len(kept)
            grade_failed = any(c.purpose == "grade" and c.error for c in ctx.llm_calls) or any(
                "grade failed" in e for e in ctx.errors
            )
            if grade_failed:
                covered = fast_ok
                reason = f"grader failed; fell back to fast rule ({fast_reason})"
            else:
                missing = missing_entities(q, chunks, labels_known)
                covered = n_rel >= s.coverage_threshold and not missing
                reason = f"{n_rel} chunk(s) judged relevant (need {s.coverage_threshold})"
                if missing:
                    reason = f"names {', '.join(missing)}, which isn't in your documents"

        labels = list(dict.fromkeys(chunk_label(c) for c in kept))
        docs = [Document(page_content=c.text, metadata=c.metadata) for c in kept]
        return Grounding(
            context=format_context(docs),
            kept=kept,
            labels=labels,
            n_relevant=n_rel,
            covered=covered,
            graded=grade,
            degraded=ctx.degraded,
            errors=list(ctx.errors),
            reason=reason,
        )
