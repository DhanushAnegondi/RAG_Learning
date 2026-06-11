"""NVIDIA NIM factories. Imports are lazy so the package imports without the heavy SDK,
and so tests can monkeypatch these factories instead of hitting the network."""
from __future__ import annotations

from .config import get_settings


def get_llm(**kwargs):
    """ChatNVIDIA for generation + grading. temperature=0 for deterministic grading."""
    from langchain_nvidia_ai_endpoints import ChatNVIDIA

    s = get_settings()
    return ChatNVIDIA(model=s.llm_model, temperature=0, **kwargs)


def get_embeddings():
    """NVIDIAEmbeddings. truncate='END' avoids hard errors on chunks longer than the model max.
    NVIDIAEmbeddings sets input_type='query' for embed_query and 'passage' for embed_documents."""
    from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings

    s = get_settings()
    return NVIDIAEmbeddings(model=s.embed_model, truncate="END")
