"""M0 smoke test — confirm the NVIDIA key + model actually work before building on top.

Run (PowerShell), after copying .env.example -> .env and pasting your key:
    $env:PYTHONPATH = "src"; .\.venv\Scripts\python.exe scripts\smoke_test.py
Done-when: it prints a reply from the model.
"""
from __future__ import annotations

from crag.config import get_settings
from crag.llm import get_llm


def main() -> int:
    if not get_settings().nvidia_api_key:
        print("NVIDIA_API_KEY not set. Copy .env.example to .env and paste your nvapi- key.")
        return 2
    resp = get_llm().invoke("Reply with exactly: CRAG smoke test OK")
    print(getattr(resp, "content", resp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
