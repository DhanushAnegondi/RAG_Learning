"""LLM factory + model registry. Lets the UI/CLI pick the answer model, and caches clients so we
don't re-validate the model on every call (ChatNVIDIA checks the catalog at construction)."""
from __future__ import annotations

import os

# Verified responding on the user's NVIDIA key (probed 2026-06-11 via scripts/probe_models.py).
MODELS: dict[str, str] = {
    "NVIDIA Nemotron 3.5 Bolt E4B": "nvidia/nemotron-3.5-bolt-e4b",
    "Quality — Llama 3.3 70B (default)": "meta/llama-3.3-70b-instruct",
    "Balanced — Llama 3.1 70B": "meta/llama-3.1-70b-instruct",
    "Balanced — Mixtral 8x7B": "mistralai/mixtral-8x7b-instruct-v0.1",
    "Fast — Llama 3.1 8B": "meta/llama-3.1-8b-instruct",
}
DEFAULT_MODEL = "meta/llama-3.3-70b-instruct"
V2_MODEL = "nvidia/nemotron-3.5-bolt-e4b"
FAST_MODEL = "meta/llama-3.1-8b-instruct"  # used for grading + suggesting (cheap, quick)

_CACHE: dict[tuple, object] = {}


def chat(model: str | None = None, temperature: float = 0.0):
    """Return a (cached) ChatNVIDIA for the given model id."""
    model = model or os.getenv("EXP_LLM_MODEL") or DEFAULT_MODEL
    key = (model, temperature)
    if key not in _CACHE:
        from langchain_nvidia_ai_endpoints import ChatNVIDIA

        options = {"chat_template_kwargs": {"enable_thinking": False}} if model == "nvidia/nemotron-3.5-bolt-e4b" else {}
        _CACHE[key] = ChatNVIDIA(model=model, temperature=temperature, **options)
    return _CACHE[key]
