# Experience Copilot

Ask a question about *your* experience ("What data pipeline have you built that you're proud of?",
"Why this company?") and get a natural, human-sounding answer **grounded in your own documents** —
with controls for answer **length** (short / medium / long) and **tone** (formal / professional /
conversational / humanized). Built for interview prep and writing about yourself faster.

It **reuses the Corrective RAG (`crag`) package** from `../corrective-rag` as its grounding engine
(retrieve your relevant experience → grade each chunk for relevance), then adds the new parts CRAG
doesn't have: a **persona** (your voice), **controllable generation** (length + tone), and a UI.

## How it differs from CRAG
- **No blind web fallback.** For personal-experience answers you never want random web text in
  "your" answer. When your KB doesn't cover a question, the copilot **tells you and asks for a few
  bullets** (then drafts from them). A web-research toggle stays available for company/factual
  questions only.
- **Persona-conditioned, controllable generation** — the new concept here (CRAG's `generate` is plain).

## What YOU provide (the copilot can't invent these)
1. `profile/persona.md` — who you are, your role, and voice/style guidance. **Fill this in.**
2. `profile/style_examples.md` — 2–3 samples of your *own* writing so it matches your voice. **Fill this in.**
3. `data/corpus/` — your experience docs (projects, achievements, runbooks, company research) as
   `.md` / `.txt` / `.pdf`. Drop them here.

## Milestones
- **M1 — Grounding (reuse CRAG).** `engine.ground(question)` retrieves + grades over YOUR corpus and
  reports whether it's covered. Done-when: relevant chunks come back for an in-KB question.
- **M2 — Voice + controls.** `answer.generate_answer(question, context, persona, length, tone)` —
  the core. Done-when: same question, different length/tone, all sounding like you.
- **M3 — Auto-suggest + routing.** `suggest` picks a sensible length/tone from the question (user can
  override). No-coverage → ask-you (personal) or optional web (research).
- **M4 — Streamlit UI.** Question box + length/tone dropdowns + source toggle + answer + "needs more
  info" prompt. Done-when: a usable website.
- **M5 — Polish (stretch).** Answer history, copy button, save favourite answers.

## Quickstart (after you fill the profile + corpus)
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e ..\corrective-rag   # reuse the crag engine
Copy-Item .env.example .env   # paste your NVIDIA_API_KEY (same key as CRAG)
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m copilot.cli ingest
.\.venv\Scripts\python.exe -m copilot.cli answer "What data pipeline are you most proud of?" --length medium --tone humanized
# M4:
.\.venv\Scripts\python.exe -m streamlit run app.py
```

> Honesty: use this to **draft and practice**, not to read answers verbatim in a live interview.
> For "why this company", the authentic version has to be yours — the tool gets you 80% there.
