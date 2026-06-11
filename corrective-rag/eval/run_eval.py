"""M5 eval — naive RAG vs CRAG, scored with ragas (faithfulness, context_precision).

STATUS: NOT YET RUN. This is the M5 stretch harness. Running it requires:
  1. pip install -r requirements-eval.txt   (ragas + its deps)
  2. A live NVIDIA_API_KEY and an ingested corpus (python -m crag.cli ingest)
  3. PYTHONPATH including src/  (or: pip install -e .)

ragas judges answers with an LLM + embeddings. This project has no OpenAI key, so we point ragas at
NVIDIA via LangChain wrappers. ragas changes symbols between minor versions — if an import below
fails, check your installed ragas version. Do NOT report any score until this script actually runs;
the resume bullet stays qualitative until then (see docs/PRD.md M5 gate).
"""
from __future__ import annotations

import json
from pathlib import Path

from crag.config import get_settings
from crag.graph import build_graph
from crag.llm import get_embeddings, get_llm
from crag.nodes.generate import generate
from crag.nodes.retrieve import retrieve

EVAL_PATH = Path(__file__).parent / "eval_set.jsonl"


def load_eval() -> list[dict]:
    with open(EVAL_PATH, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def naive_rag(question: str):
    """Baseline: retrieve -> generate, no grading, no correction (the M1 path)."""
    state = retrieve({"question": question, "steps": []})
    contexts = [d.page_content for d in state.get("documents", [])]
    answer = generate({"question": question, "documents": state.get("documents", [])})["generation"]
    return answer, contexts


def crag(question: str):
    """Full CRAG graph; returns answer, the contexts it actually used, and the route taken."""
    result = build_graph().invoke({"question": question, "steps": []})
    docs = result.get("documents", [])
    grades = result.get("grades", [])
    kept = [d for d, g in zip(docs, grades) if g] if grades else list(docs)
    kept += result.get("web_results", [])
    contexts = [d.page_content for d in kept]
    return result.get("generation", ""), contexts, result.get("steps", [])


def _dataset(rows: list[dict], runner, is_crag: bool):
    from datasets import Dataset

    cols = {"question": [], "answer": [], "contexts": [], "ground_truth": []}
    for r in rows:
        ans, ctx = (runner(r["question"])[:2]) if is_crag else runner(r["question"])
        cols["question"].append(r["question"])
        cols["answer"].append(ans)
        cols["contexts"].append(ctx)
        cols["ground_truth"].append(r["ground_truth"])
    return Dataset.from_dict(cols)


def _score(dataset):
    from ragas import evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import context_precision, faithfulness

    result = evaluate(
        dataset,
        metrics=[faithfulness, context_precision],
        llm=LangchainLLMWrapper(get_llm()),
        embeddings=LangchainEmbeddingsWrapper(get_embeddings()),
    )
    df = result.to_pandas()
    return {m: float(df[m].mean()) for m in ("faithfulness", "context_precision")}


def main() -> int:
    if not get_settings().nvidia_api_key:
        print("NVIDIA_API_KEY not set. Copy .env.example to .env and paste your key.")
        return 2
    rows = load_eval()
    print(f"Loaded {len(rows)} eval questions.")
    print("Scoring naive RAG ...")
    naive = _score(_dataset(rows, naive_rag, is_crag=False))
    print("Scoring CRAG ...")
    crag_scores = _score(_dataset(rows, crag, is_crag=True))

    print("\n| metric | naive RAG | CRAG |")
    print("|---|---|---|")
    for m in ("faithfulness", "context_precision"):
        print(f"| {m} | {naive[m]:.3f} | {crag_scores[m]:.3f} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
