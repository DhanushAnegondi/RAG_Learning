"""Experience Copilot: Streamlit UI.

Run:  streamlit run app.py   (after `copilot ingest`; the API key lives in the repo-root .env)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import streamlit as st

from copilot.answer import generate_answer
from copilot.config import LENGTHS, MODELS, ROOT_ENV, TONES, get_settings
from copilot.engine import ground
from copilot.suggest import suggest_style
from copilot.web import research_web

st.set_page_config(page_title="Experience Copilot", page_icon="🗣️")
st.title("🗣️ Experience Copilot")
st.caption("Answers about your experience, grounded in your own documents, written in your voice.")

settings = get_settings()
if not settings.key_configured:
    st.error(
        "NVIDIA_API_KEY is missing or still a placeholder. "
        f"Put your key in `{ROOT_ENV}` (shared with corrective-rag), then reload."
    )
    st.stop()

with st.sidebar:
    st.header("Controls")
    model_label = st.selectbox("Answer model", list(MODELS), index=0)
    model_id = MODELS[model_label]
    length = st.selectbox("Length", LENGTHS, index=0, help="'auto' lets the model choose.")
    tone = st.selectbox("Tone", TONES, index=0)
    fast = st.checkbox(
        "Fast mode (skip relevance grading)",
        value=True,
        help="No LLM call per chunk. Coverage is still checked with retrieval signals.",
    )
    allow_web = st.checkbox(
        "Add web research (not from my documents)",
        value=False,
        help="Opt-in. For company/factual questions; off for personal-experience answers.",
    )
    st.divider()
    st.caption(f"Persona: `{os.path.basename(settings.persona_path)}`")
    st.caption(f"Docs: `{settings.corpus_dir}`")

question = st.text_area(
    "Question about your experience",
    placeholder="e.g. What billing pipeline are you most proud of?",
    height=90,
)
notes = st.text_area(
    "Extra notes (optional)",
    placeholder="A few bullets to ground on if your documents are thin.",
    height=70,
)

if st.button("Draft my answer", type="primary") and question.strip():
    chosen_len, chosen_tone = length, tone
    if length == "auto" or tone == "auto":
        with st.spinner("Picking length and tone..."):
            sug = suggest_style(question, settings=settings)
        chosen_len = sug.length if length == "auto" else length
        chosen_tone = sug.tone if tone == "auto" else tone
        st.info(f"Auto-picked **{chosen_len}** length, **{chosen_tone}** tone")

    try:
        with st.spinner("Grounding in your documents..."):
            g = ground(question, grade=not fast, settings=settings)
        web_ctx = ""
        if allow_web:
            with st.spinner("Researching the web..."):
                web = research_web(question, settings)
            web_ctx = web.context
            if web.degraded or web.errors:
                st.warning("Web research degraded: " + "; ".join(web.errors or ["search failed"]))
            elif not web_ctx:
                st.caption("Web research returned nothing.")
        with st.spinner("Writing the answer..."):
            res = generate_answer(
                question, g, length=chosen_len, tone=chosen_tone, extra_notes=notes.strip(),
                web_context=web_ctx, model=model_id, settings=settings,
            )
    except ValueError as exc:  # empty/oversized question
        st.error(str(exc))
        st.stop()

    mode = "fast (no grading)" if fast else "graded"
    if g.covered:
        st.success(f"Coverage ({mode}): covered. {g.reason}")
    else:
        st.warning(f"Coverage ({mode}): your documents do not strongly cover this. {g.reason}")
        if not notes.strip() and not web_ctx:
            st.caption("Tip: add a few bullets above, or enable web research in the sidebar.")

    if not res.text:
        st.error("Generation failed: " + "; ".join(res.errors or res.warnings))
        st.stop()

    st.markdown("### Draft")
    st.write(res.text)
    for w in res.warnings:
        st.warning(w)
    if g.degraded or res.errors:
        st.warning("Degraded: some components failed. Details below.")
        with st.expander("Errors"):
            st.code("\n".join(dict.fromkeys([*g.errors, *res.errors])) or "(none recorded)")

    with st.expander(f"Sources used: {', '.join(g.labels) or 'none'}"):
        for c in g.kept:
            body = c.text.split("\n", 1)[-1]
            st.markdown(f"**{c.metadata.get('experience', '?')}** `{c.metadata.get('source', '')}`")
            st.caption(body[:300] + ("..." if len(body) > 300 else ""))
    st.caption(
        f"model: `{res.model_used or model_id}` | mode: {mode} | web: {'yes' if web_ctx else 'no'} "
        f"| {res.length}/{res.tone} | regenerated: {res.retries}"
    )
    st.caption("Draft to practice with. Make it yours before you use it.")
