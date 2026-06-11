"""CLI to exercise the copilot before the UI exists.

    copilot ingest
    copilot answer "What pipeline are you most proud of?" --length medium --tone humanized
    copilot answer "Tell me about yourself"            # length/tone auto-picked
"""
from __future__ import annotations

import argparse
import sys

from .answer import generate_answer
from .config import LENGTHS, TONES, get_settings
from .engine import ground
from .suggest import suggest_style


def _ingest() -> int:
    from .ingest import build_index

    s = build_index()
    print(f"Indexed {s.corpus_dir} -> {s.persist_dir}")
    return 0


def _answer(question, length, tone, notes, model, fast) -> int:
    if length == "auto" or tone == "auto":
        sug = suggest_style(question)
        length = sug.length if length == "auto" else length
        tone = sug.tone if tone == "auto" else tone
        print(f"(auto-picked length={length}, tone={tone})")

    g = ground(question, grade=not fast)
    if g["graded"] and not g["covered"]:
        print(
            "\n[!] Your documents don't strongly cover this question "
            f"({g['n_relevant']} relevant chunk(s)). Add notes with --notes or more docs in data/corpus."
        )
    answer = generate_answer(
        question, g["context"], length=length, tone=tone, extra_notes=notes, model=model
    )
    print("\n" + answer)
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
    a.add_argument("--model", default=None, help="Model id (default: quality). See copilot.llm.MODELS")
    a.add_argument("--fast", action="store_true", help="Skip per-chunk grading for a faster answer")

    args = p.parse_args(argv)
    if not get_settings().nvidia_api_key:
        print("NVIDIA_API_KEY not set. Copy .env.example to .env and paste your key.", file=sys.stderr)
        return 2
    if args.cmd == "ingest":
        return _ingest()
    if args.cmd == "answer":
        return _answer(args.question, args.length, args.tone, args.notes, args.model, args.fast)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
