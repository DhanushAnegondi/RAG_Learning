"""CLI.

    copilot ingest
    copilot answer "What billing pipeline are you most proud of?" --length medium --tone humanized
    copilot answer "Tell me about yourself"            # length/tone auto-picked

Exit codes: 0 ok, 1 generation failed, 2 API key missing/placeholder.
"""
from __future__ import annotations

import argparse
import sys

from .answer import generate_answer
from .config import LENGTHS, ROOT_ENV, TONES, get_settings
from .engine import ground
from .ingest import build_index
from .suggest import suggest_style
from .web import research_web


def _ingest(settings) -> int:
    try:
        r = build_index(settings)
    except ValueError as exc:  # no ingestable documents
        print(f"Ingest failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Indexed {settings.corpus_dir} -> {settings.persist_dir}: "
        f"{len(r.added_files)} added, {len(r.updated_files)} updated, "
        f"{len(r.removed_files)} removed, {len(r.unchanged_files)} unchanged "
        f"({r.chunks_embedded} chunks embedded)"
    )
    return 0


def _answer(settings, question, length, tone, notes, model, fast, web) -> int:
    if length == "auto" or tone == "auto":
        sug = suggest_style(question, settings=settings)
        length = sug.length if length == "auto" else length
        tone = sug.tone if tone == "auto" else tone
        print(f"(auto-picked length={length}, tone={tone})")

    g = ground(question, grade=not fast, settings=settings)
    mode = "fast" if fast else "graded"
    print(f"coverage ({mode}): {'covered' if g.covered else 'NOT covered'}; {g.reason}")
    if not g.covered:
        print("[!] Your documents don't strongly cover this. Add --notes or more docs.")
    web_ctx = ""
    if web:
        w = research_web(question, settings)
        web_ctx = w.context
        print(f"web research: {len(w.sources)} source(s) (NOT from your documents)")
        if w.degraded or w.errors:
            print("[web degraded] " + "; ".join(w.errors or ["web search failed"]), file=sys.stderr)
    res = generate_answer(
        question, g, length=length, tone=tone, extra_notes=notes, web_context=web_ctx,
        model=model, settings=settings,
    )
    if not res.text:
        print("Generation failed: " + "; ".join(res.errors or res.warnings), file=sys.stderr)
        return 1
    print("\n" + res.text)
    print(f"\nsources: {', '.join(g.labels) or '(none)'} | model: {res.model_used}")
    for w_ in res.warnings:
        print(f"[warning] {w_}")
    if g.degraded or res.errors:
        print("[degraded] some components failed; see errors", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="copilot", description="Experience Copilot")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest", help="Embed your experience docs into the index")
    a = sub.add_parser("answer", help="Answer a question in your voice")
    a.add_argument("question")
    a.add_argument("--length", default="auto", choices=LENGTHS)
    a.add_argument("--tone", default="auto", choices=TONES)
    a.add_argument("--notes", default="", help="Extra detail to ground on when your docs are thin")
    a.add_argument("--model", default=None, help="Answer model id (default: EXP_ANSWER_MODEL)")
    a.add_argument("--fast", action="store_true", help="Skip per-chunk grading for a faster answer")
    a.add_argument("--web", action="store_true", help="Opt in to web research (not from your KB)")

    args = p.parse_args(argv)
    settings = get_settings()
    if not settings.key_configured:
        print(
            f"NVIDIA_API_KEY is missing or still a placeholder. Put your key in {ROOT_ENV}.",
            file=sys.stderr,
        )
        return 2
    if args.cmd == "ingest":
        return _ingest(settings)
    return _answer(
        settings, args.question, args.length, args.tone, args.notes, args.model, args.fast, args.web
    )


if __name__ == "__main__":
    raise SystemExit(main())
