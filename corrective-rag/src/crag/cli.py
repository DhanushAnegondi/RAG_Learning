"""CLI: `crag ingest` builds the index; `crag ask "..."` runs the graph and shows the route.

Both subcommands need a live NVIDIA_API_KEY (embeddings + LLM). The pytest suite does NOT.
"""
from __future__ import annotations

import argparse
import sys

from .config import get_settings


def _ingest() -> int:
    from .ingest import build_index

    s = get_settings()
    build_index()
    print(f"Indexed corpus from {s.corpus_dir} -> {s.persist_dir}")
    return 0


def _ask(question: str) -> int:
    from .graph import build_graph

    result = build_graph().invoke({"question": question, "steps": []})
    route = " -> ".join(result.get("steps", []))
    print(f"\nRoute: {route}")
    print(f"\nAnswer:\n{result.get('generation', '(no answer)')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crag", description="Corrective RAG CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest", help="Build the Chroma index from data/corpus")
    ask = sub.add_parser("ask", help="Ask a question through the CRAG graph")
    ask.add_argument("question", help="The question to answer")

    args = parser.parse_args(argv)
    if not get_settings().nvidia_api_key:
        print("ERROR: NVIDIA_API_KEY is not set. Copy .env.example to .env and paste your key.", file=sys.stderr)
        return 2
    if args.cmd == "ingest":
        return _ingest()
    if args.cmd == "ask":
        return _ask(args.question)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
