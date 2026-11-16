"""Results page is built from captured files only."""

import json

from cinebridge.report import build_page


def sprint(root, name: str, title: str, **meta):
    d = root / name
    for sub in ("metrics", "charts", "tables", "run"):
        (d / sub).mkdir(parents=True)
    (d / "meta.json").write_text(
        json.dumps({"title": title, "goal": "g", "pattern": "p", **meta}, ensure_ascii=False),
        encoding="utf-8",
    )
    return d


def test_page_lists_sprints_newest_first_with_natural_order(tmp_path):
    sprint(tmp_path, "sprint-9", "MARKER-NINE-QX")
    sprint(tmp_path, "sprint-10", "MARKER-TEN-QX")
    sprint(tmp_path, "sprint-2", "MARKER-TWO-QX")
    page = build_page(tmp_path)
    assert page.index("MARKER-TEN-QX") < page.index("MARKER-NINE-QX") < page.index("MARKER-TWO-QX")


def test_page_shows_terminal_output_and_csv_cells_escaped(tmp_path):
    d = sprint(tmp_path, "sprint-01", "t", findings=["<b>FINDING-QX</b>"])
    (d / "run" / "green.out").write_text("12 passed <script>RUN-QX</script>", encoding="utf-8")
    (d / "metrics" / "01_m.csv").write_text("col\n<i>CELL-QX</i>\n", encoding="utf-8")
    page = build_page(tmp_path)
    assert "12 passed &lt;script&gt;RUN-QX&lt;/script&gt;" in page
    assert "&lt;i&gt;CELL-QX&lt;/i&gt;" in page
    assert "&lt;b&gt;FINDING-QX&lt;/b&gt;" in page
    assert "<script>RUN-QX" not in page


def test_page_keeps_telugu_script(tmp_path):
    d = sprint(tmp_path, "sprint-01", "t")
    telugu = "బాహుబలి"
    (d / "metrics" / "01_m.csv").write_text(f"original_title\n{telugu}\n", encoding="utf-8")
    page = build_page(tmp_path)
    assert telugu in page
    assert "charset='utf-8'" in page


def test_page_shows_table_schema_count_and_sample(tmp_path):
    d = sprint(tmp_path, "sprint-01", "t", table_order=["b_table", "a_table"])
    for name in ("a_table", "b_table"):
        (d / "tables" / f"{name}.json").write_text(
            json.dumps(
                {
                    "table": name,
                    "row_count": 1234567,
                    "columns": [["movie_id", "BIGINT"]],
                    "sample": [[f"SAMPLE-{name}"]],
                }
            ),
            encoding="utf-8",
        )
    page = build_page(tmp_path)
    assert "1,234,567 rows" in page
    assert "BIGINT" in page
    assert page.index("SAMPLE-b_table") < page.index("SAMPLE-a_table")


def test_page_embeds_charts_and_caption_titles(tmp_path):
    d = sprint(
        tmp_path,
        "sprint-01",
        "t",
        captions={
            "01_c.png": {"title": "CHART-TITLE-QX"},
            "01_m.csv": {"title": "CSV-TITLE-QX", "note": "NOTE-QX"},
        },
    )
    (d / "charts" / "01_c.png").write_bytes(b"\x89PNG fake")
    (d / "metrics" / "01_m.csv").write_text("a\n1\n", encoding="utf-8")
    page = build_page(tmp_path)
    assert "data:image/png;base64," in page
    assert "CHART-TITLE-QX" in page and "CSV-TITLE-QX" in page and "NOTE-QX" in page


def test_page_escapes_review_limits_commands_and_caption_text(tmp_path):
    d = sprint(
        tmp_path,
        "sprint-01",
        "t",
        commands=["make <b>CMD-QX</b>"],
        limits=["<i>LIMIT-QX</i>"],
        scripts=["src/<u>SCRIPT-QX</u>.py"],
        captions={"01_m.csv": {"title": "<s>TITLE-QX</s>", "note": "<em>NOTE-QX</em>"}},
    )
    (d / "review.md").write_text("FAIL <script>REVIEW-QX</script>", encoding="utf-8")
    (d / "metrics" / "01_m.csv").write_text("a\n1\n", encoding="utf-8")
    page = build_page(tmp_path)
    for raw in (
        "<b>CMD-QX",
        "<i>LIMIT-QX",
        "<script>REVIEW-QX",
        "<s>TITLE-QX",
        "<em>NOTE-QX",
        "<u>SCRIPT-QX",
    ):
        assert raw not in page, raw
    for marker in ("CMD-QX", "LIMIT-QX", "REVIEW-QX", "TITLE-QX", "NOTE-QX", "SCRIPT-QX"):
        assert marker in page, marker
