"""Experience Copilot — Streamlit UI.

Run:  streamlit run app.py   (after filling profile/ + data/corpus/ and setting NVIDIA_API_KEY)
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import streamlit as st

from copilot.answer import generate_answer
from copilot.config import LENGTHS, TONES, get_settings
from copilot.engine import ground
from copilot.llm import MODELS
from copilot.suggest import suggest_style

st.set_page_config(page_title="Experience Copilot", page_icon="🗣️")
st.title("🗣️ Experience Copilot")
st.caption("Answers about your experience, grounded in your own documents, written in your voice.")
from copilot.retrieval_v2 import index_dir
index_path = index_dir() / 'index.json'
if index_path.exists():
    snapshot = json.loads(index_path.read_text(encoding='utf-8'))
    source_count = len({r['metadata']['source'] for r in snapshot['chunks']})
    st.info(f"Experience library: {source_count} selected source documents. Answers cite their supporting passages.")
    st.caption('Search mode: ' + ('keyword fallback' if snapshot.get('retrieval_mode') == 'keyword' else 'hybrid retrieval'))
else:
    st.warning("Your personal search index is being prepared. The question screen is available; answers will work after indexing completes.")

settings = get_settings()
if not settings.nvidia_api_key:
    st.error("NVIDIA_API_KEY is not set. Copy `.env.example` to `.env` and paste your key, then reload.")
    st.stop()

with st.sidebar:
    st.header("Controls")
    version = st.selectbox("RAG version", ("v1", "v2"), index=1,
                           help="V1: original baseline. V2: reviewed evidence, hybrid retrieval and checked citations.")
    employer = st.text_input("Employer filter (V2, optional)")
    model_label = st.selectbox("Answer model", list(MODELS), index=0)
    model_id = MODELS[model_label]
    length = st.selectbox("Length", LENGTHS, index=0,
                         help="V1 auto: model chooses. V2 auto: medium length and humanized tone.")
    tone = st.selectbox("Tone", TONES, index=0)
    fast = st.checkbox(
        "Fast mode (skip relevance grading)",
        value=True,
        disabled=version == "v2",
        help="Faster: retrieves your docs and answers directly, without an LLM call per chunk.",
    )
    allow_web = st.checkbox(
        "Allow web research when my docs don't cover it",
        value=False,
        disabled=version == "v2",
        help="Useful for company/factual questions. Off for personal-experience answers.",
    )
    st.divider()
    st.caption(f"Persona: `{os.path.basename(settings.persona_path)}`")
    st.caption(f"Docs: `{settings.corpus_dir}`")

question = st.text_area(
    "Question about your experience",
    placeholder="e.g. What data pipeline are you most proud of?",
    height=90,
)
notes = st.text_area(
    "Extra notes (optional)",
    placeholder="A few bullets to ground on if your documents are thin.",
    height=70,
)

if st.button("Draft my answer", type="primary") and question.strip():
    if version == "v2":
        from copilot.pipeline import draft
        if notes.strip():
            st.info("V2 uses reviewed corpus evidence. Add these notes to a source document and review its manifest entry first.")
        try:
            with st.spinner("Finding evidence and checking the draft…"):
                result = draft(question, employer=employer.strip() or None, model=model_id,
                               length="medium" if length == "auto" else length,
                               tone="humanized" if tone == "auto" else tone)
        except FileNotFoundError:
            st.error("Build the V2 index first: copilot ingest --version v2. See docs/TESTING.md.")
            st.stop()
        if result.get("verified"):
            st.markdown(result["answer"])
        else:
            st.warning(result["answer"])
        with st.expander("Supporting evidence"):
            for source in result["sources"]:
                st.write(f"[{source['id']}] {source['employer']} — {source['project']}")
                st.caption(f"{source['source']} · version {source['version']} · ownership: {source['ownership']}")
            st.text(result["context"])
        st.caption("V2 · reviewed sources · hybrid retrieval · model-checked draft (review it yourself before use).")
        st.stop()
    chosen_len, chosen_tone = length, tone
    if length == "auto" or tone == "auto":
        with st.spinner("Picking length and tone…"):
            sug = suggest_style(question)
        chosen_len = sug.length if length == "auto" else length
        chosen_tone = sug.tone if tone == "auto" else tone
        st.info(f"Auto-picked **{chosen_len}** length, **{chosen_tone}** tone")

    with st.spinner("Grounding in your documents…"):
        g = ground(question, grade=not fast)

    context = g["context"]
    used_web = False
    if g["graded"] and not g["covered"]:
        st.warning(f"Your documents don't strongly cover this ({g['n_relevant']} relevant chunk(s)).")
        if allow_web:
            with st.spinner("Researching the web…"):
                from crag.nodes.web_search import web_search

                web_docs = web_search({"question": question}).get("web_results", [])
            if web_docs:
                used_web = True
                context = (context + "\n\n# Web research (not from your KB)\n"
                           + "\n\n".join(d.page_content for d in web_docs)).strip()
        elif not notes.strip():
            st.caption("Tip: add a few bullets above, or enable web research in the sidebar.")

    st.markdown("### Draft")
    stream = generate_answer(
        question, context, length=chosen_len, tone=chosen_tone,
        extra_notes=notes.strip(), model=model_id, stream=True,
    )
    st.write_stream(stream)
    st.caption(
        f"model: `{model_id}` · mode: {'fast (no grading)' if fast else 'graded'} · "
        f"web: {'yes' if used_web else 'no'} · {chosen_len}/{chosen_tone}"
    )
    st.caption("Draft to practice with — make it yours before you use it.")
