"""Entry point: first step of make diagram.

Fills the counts in results/<sprint>/arch.template.html from captured run files and writes
arch.src.html, so no number in the diagram is typed by hand.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(sprint: str = "sprint-01") -> int:
    d = ROOT / "results" / sprint
    run = d / "run"
    scope = json.loads((d / "tables" / "mart_scope_audit.json").read_text(encoding="utf-8"))
    names = [c[0] for c in scope["columns"]]
    landed = sum(row[names.index("landed_rows")] for row in scope["sample"])
    counts = {
        table: json.loads((d / "tables" / f"{table}.json").read_text(encoding="utf-8"))["row_count"]
        for table in ("raw_ratings", "stg_movies")
    }
    pipeline_out = (run / "pipeline.out").read_text(encoding="utf-8")
    filled = re.search(r"filled ([\d,]+) values", pipeline_out).group(1)
    passed = re.search(r"(\d+) passed", (run / "green.out").read_text(encoding="utf-8")).group(1)
    killed = re.search(
        r"(\d+)/(\d+) mutations killed", (run / "mutation.out").read_text(encoding="utf-8")
    )
    values = {
        "N_LANDED": f"{landed:,}",
        "N_RATINGS": f"{counts['raw_ratings'] / 1e6:.1f}M",
        "N_FILMS": f"{counts['stg_movies']:,}",
        "N_FILLED": filled,
        "N_TESTS": passed,
        "N_MUTANTS": killed.group(1),
    }
    html = (d / "arch.template.html").read_text(encoding="utf-8")
    for key, value in values.items():
        html = html.replace(f"%%{key}%%", value)
    (d / "arch.src.html").write_text(html, encoding="utf-8")
    print(f"wrote results/{sprint}/arch.src.html with {values}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
