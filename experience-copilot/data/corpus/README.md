# Your experience corpus

Drop your own documents here, one folder per employer or experience (`Acme/...`; `interview/Acme/...`
also maps to `Acme`), as `.md`, `.txt`, or `.pdf`:
- Project write-ups, architecture notes, achievements, runbooks
- Resume / bio paragraphs
- Company research notes (for "why this company" type questions)

Then run `copilot ingest` to (re)build the index. Re-run with changed files and only those are
re-embedded.

These files are **gitignored** (only this README is tracked); your real content stays local. A fictional
sample corpus lives in `../../examples/`.
