"""Results page: generated from captured files, every sprint, newest first, output verbatim."""

import json
from pathlib import Path

from weatherwise.report import build_page


def make_sprint(root: Path, name: str, goal: str, out_text: str) -> None:
    d = root / name
    (d / "run").mkdir(parents=True)
    (d / "tables").mkdir()
    (d / "meta.json").write_text(
        json.dumps({"title": name, "goal": goal, "commands": ["make run"], "limits": ["small"]}),
        encoding="utf-8",
    )
    (d / "run" / "pipeline.out").write_text(out_text, encoding="utf-8")
    snap = {
        "table": "raw_actual_daily",
        "row_count": 11234,
        "columns": [["city", "VARCHAR"], ["tmax_c", "DOUBLE"]],
        "sample": [["bengaluru", 29.5]],
    }
    (d / "tables" / "raw_actual_daily.json").write_text(json.dumps(snap), encoding="utf-8")


def test_page_lists_sprints_newest_first(tmp_path):
    """Fails if an older sprint is shown above a newer one, or a sprint is missing."""
    make_sprint(tmp_path, "sprint-01", "first goal", "ok")
    make_sprint(tmp_path, "sprint-02", "second goal", "ok")
    html = build_page(tmp_path)
    assert html.index("second goal") < html.index("first goal")


def test_page_shows_terminal_output_verbatim_and_escaped(tmp_path):
    """Fails if output is altered or HTML in it is injected into the page unescaped."""
    make_sprint(tmp_path, "sprint-01", "g", "rows loaded: 42\n<script>x</script>")
    html = build_page(tmp_path)
    assert "rows loaded: 42" in html
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html


def test_page_shows_table_schema_count_and_sample(tmp_path):
    """Fails if a table snapshot loses its row count, column types or sample rows."""
    make_sprint(tmp_path, "sprint-01", "g", "ok")
    html = build_page(tmp_path)
    assert "raw_actual_daily" in html
    assert "11,234" in html
    assert "DOUBLE" in html
    assert "bengaluru" in html
