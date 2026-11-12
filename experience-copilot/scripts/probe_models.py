"""Probe candidate NVIDIA NIM model ids with the current key — prints which actually respond.
Run: python scripts/probe_models.py   (needs NVIDIA_API_KEY + crag installed for langchain-nvidia)
"""
from __future__ import annotations

from crag.observability import redact
from langchain_nvidia_ai_endpoints import ChatNVIDIA

CANDIDATES = [
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "nvidia/nemotron-3.5-bolt-e4b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "deepseek-ai/deepseek-v4.1-flash",
]

for m in CANDIDATES:
    try:
        ChatNVIDIA(model=m, temperature=0, max_tokens=5).invoke("hi")
        print("OK  ", m)
    except Exception as e:  # noqa: BLE001
        print("FAIL", m, "-", redact(str(e).splitlines()[0])[:90])
