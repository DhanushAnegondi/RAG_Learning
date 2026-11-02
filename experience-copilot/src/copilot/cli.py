"""CLI to exercise the copilot before the UI exists.

    copilot ingest
    copilot answer "What pipeline are you most proud of?" --length medium --tone humanized
    copilot answer "Tell me about yourself"            # length/tone auto-picked
"""
from __future__ import annotations

import argparse
from pathlib import Path
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
    ing = sub.add_parser("ingest", help="Embed your experience docs into the index")
    ing.add_argument("--version", choices=("v1", "v2"), default="v1")
    ing.add_argument("--manifest", help="V2 evidence manifest (default: corpus/evidence.json)")
    ing.add_argument("--keyword-only", action="store_true", help="V2: build local keyword index without embedding calls")
    a = sub.add_parser("answer", help="Answer a question in your voice")
    a.add_argument("question")
    a.add_argument("--length", default="auto", choices=LENGTHS)
    a.add_argument("--tone", default="auto", choices=TONES)
    a.add_argument("--notes", default="", help="Extra detail to ground on when your docs are thin")
    a.add_argument("--model", default=None, help="Model id (default: quality). See copilot.llm.MODELS")
    a.add_argument("--fast", action="store_true", help="Skip per-chunk grading for a faster answer")
    a.add_argument("--version", choices=("v1", "v2"), default="v1")
    a.add_argument("--employer", help="V2: restrict evidence to this employer")

    ev = sub.add_parser("evaluate", help="Validate a question set or compare V1/V2 live")
    ev.add_argument("--dataset", default=str(Path(__file__).resolve().parents[2] / "eval/questions.jsonl"))
    ev.add_argument("--live", action="store_true", help="Use NVIDIA embeddings/LLM against isolated synthetic indexes")
    ev.add_argument("--answers", action="store_true", help="Also generate answers (extra API calls)")
    ev.add_argument("--limit", type=int, default=None)
    ev.add_argument("--model", default=None)
    ev.add_argument("--output", default="eval/results/comparison.json")

    args = p.parse_args(argv)
    if args.cmd == "evaluate":
        from .evaluation import run
        return run(args)
    if not get_settings().nvidia_api_key:
        print("NVIDIA_API_KEY not set. Copy .env.example to .env and paste your key.", file=sys.stderr)
        return 2
    if args.cmd == "ingest":
        if args.version == "v2":
            from .retrieval_v2 import build_index
            print(build_index(manifest=args.manifest, keyword_only=args.keyword_only))
            return 0
        return _ingest()
    if args.cmd == "answer":
        if args.version == "v2":
            if args.fast or args.notes:
                p.error("V2 requires evidence checking; add reviewed notes to the corpus instead of --fast/--notes")
            from .pipeline import draft
            result = draft(args.question, employer=args.employer, model=args.model,
                           length="medium" if args.length == "auto" else args.length,
                           tone="humanized" if args.tone == "auto" else args.tone)
            print(result["answer"])
            for source in result["sources"]:
                print(f"[{source['id']}] {source['source']} ({source['employer']}, {source['version']})")
            return 0 if result.get("verified") else 3
        return _answer(args.question, args.length, args.tone, args.notes, args.model, args.fast)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
