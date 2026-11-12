"""CLI: `crag ingest [--rebuild]`, `crag ask "q" [--json]`, `crag serve [--host --port]`.

Every subcommand needs a real NVIDIA key (embeddings + LLM). A missing or placeholder key is a
clear message on stderr and exit code 2, not a 401 from the provider.
"""

from __future__ import annotations

import argparse
import sys

from .config import get_settings

KEY_MESSAGE = (
    "ERROR: NVIDIA_API_KEY is not set (or is still the PASTE_ placeholder). "
    "Put your key in the repo-root .env (RAG_Learning/.env)."
)


def _ingest(rebuild: bool) -> int:
    from .ingest import build_index

    s = get_settings()
    r = build_index(s, rebuild=rebuild)
    print(f"Indexed {s.corpus_dir} -> {s.persist_dir}")
    print(
        f"files: added={len(r.added_files)} updated={len(r.updated_files)} "
        f"removed={len(r.removed_files)} unchanged={len(r.unchanged_files)}"
    )
    print(f"chunks: embedded={r.chunks_embedded} deleted={r.chunks_deleted}")
    return 0


def _ask(question: str, as_json: bool) -> int:
    from .pipeline import answer

    try:
        a = answer(question)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if as_json:
        print(a.model_dump_json(indent=2))
        return 0
    print(f"\nAnswer:\n{a.answer}")
    print(f"\nRoute: {a.route}")
    for c in a.citations:
        where = c.url or (f"{c.source} > {c.section}" if c.section else c.source)
        print(f"  [{c.id}] {where}")
    if a.degraded:
        print("Degraded: yes")
    for e in a.errors:
        print(f"  error: {e}")
    print(f"Trace: {a.trace_id}")
    return 0


def _serve(host: str, port: int) -> int:
    import uvicorn

    from .api import create_app

    uvicorn.run(create_app(), host=host, port=port)
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp1252; answers routinely contain characters it cannot encode.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="crag", description="Corrective RAG CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ing = sub.add_parser("ingest", help="Build/refresh the index from the corpus")
    ing.add_argument("--rebuild", action="store_true", help="Re-embed everything")
    ask = sub.add_parser("ask", help="Ask a question through the CRAG graph")
    ask.add_argument("question")
    ask.add_argument("--json", action="store_true", help="Print the full Answer as JSON")
    srv = sub.add_parser("serve", help="Run the HTTP API")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    if not get_settings().key_configured:
        print(KEY_MESSAGE, file=sys.stderr)
        return 2
    if args.cmd == "ingest":
        return _ingest(args.rebuild)
    if args.cmd == "ask":
        return _ask(args.question, args.json)
    return _serve(args.host, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
