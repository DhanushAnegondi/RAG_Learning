"""Entry point: make results. Writes results/index.html from captured sprint files."""

from pathlib import Path

from cinebridge.report import build_page

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    out = ROOT / "results" / "index.html"
    out.write_text(build_page(ROOT / "results"), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size:,} bytes)")
