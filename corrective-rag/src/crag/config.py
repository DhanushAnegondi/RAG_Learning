"""Settings — read once from the environment (.env). No secrets hard-coded."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()  # loads .env if present; a missing .env is fine (env may be set another way)


@dataclass(frozen=True)
class Settings:
    nvidia_api_key: str | None
    llm_model: str
    embed_model: str
    top_k: int
    relevance_threshold: int
    persist_dir: str
    corpus_dir: str


def get_settings() -> Settings:
    """Build Settings from env each call (cheap; keeps tests able to monkeypatch env)."""
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return Settings(
        nvidia_api_key=os.getenv("NVIDIA_API_KEY"),
        llm_model=os.getenv("CRAG_LLM_MODEL", "meta/llama-3.3-70b-instruct"),
        embed_model=os.getenv("CRAG_EMBED_MODEL", "nvidia/nv-embedqa-e5-v5"),
        top_k=int(os.getenv("CRAG_TOP_K", "4")),
        relevance_threshold=int(os.getenv("CRAG_RELEVANCE_THRESHOLD", "2")),
        persist_dir=os.getenv("CRAG_PERSIST_DIR", os.path.join(here, "chroma_store")),
        corpus_dir=os.getenv("CRAG_CORPUS_DIR", os.path.join(here, "data", "corpus")),
    )
