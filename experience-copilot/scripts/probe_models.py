"""Probe candidate NVIDIA NIM model ids with the current key — prints which actually respond.
Run: python scripts/probe_models.py   (needs NVIDIA_API_KEY + crag installed for langchain-nvidia)
"""
from __future__ import annotations

from langchain_nvidia_ai_endpoints import ChatNVIDIA

CANDIDATES = [
    "meta/llama-3.3-70b-instruct",
    "meta/llama-3.1-8b-instruct",
    "meta/llama-3.1-70b-instruct",
    "mistralai/mistral-7b-instruct-v0.3",
    "mistralai/mixtral-8x7b-instruct-v0.1",
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "meta/llama-3.1-405b-instruct",
]

for m in CANDIDATES:
    try:
        ChatNVIDIA(model=m, temperature=0, max_tokens=5).invoke("hi")
        print("OK  ", m)
    except Exception as e:  # noqa: BLE001
        print("FAIL", m, "-", str(e).splitlines()[0][:90])
