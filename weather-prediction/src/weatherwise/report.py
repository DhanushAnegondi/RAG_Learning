"""Build results/index.html from captured sprint files. Never hand-edit the page.

Per sprint folder (results/<sprint>/):
  meta.json        title, goal, pattern, commands, scripts, findings, limits, captions
  metrics/*.csv    result tables, shown in filename order
  charts/*.png     charts, embedded
  architecture.png stack-diagram as-built (light)
  tables/*.json    warehouse snapshots: schema, row count, sample rows
  run/*.out        terminal output, shown verbatim
  review.md        ponytail review findings and fixes
  site/*.png       screenshots of the running site, embedded
"""

import base64
import csv
import json
import re
from html import escape
from pathlib import Path

CSS = """
:root{--paper:#f6f8fb;--card:#fff;--ink:#16202c;--muted:#5b6b7d;--line:#d9e1ea;--accent:#0b6bcb;
--warm:#c2410c;--cool:#0e7490;--pre:#0f1720;--pre-ink:#d7e2ee}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#0d131a;--card:#141c25;
--ink:#e4ebf3;--muted:#93a4b7;--line:#263342;--accent:#5aa9f5;--warm:#fb923c;--cool:#22d3ee;
--pre:#070b10;--pre-ink:#cfdbe8}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);
font:15px/1.55 "Geist","Segoe UI",system-ui,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:21px;margin:0}h3{font-size:16px;margin:28px 0 8px}
.sub{color:var(--muted);margin:0 0 20px}
.sprint{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:20px;
margin:0 0 28px}
.tag{display:inline-block;font:12px "JetBrains Mono",Consolas,monospace;color:var(--accent);
border:1px solid var(--line);border-radius:4px;padding:1px 6px;margin-right:6px}
ul.findings li{margin:4px 0}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:6px}
table{border-collapse:collapse;width:100%;font:13px "JetBrains Mono",Consolas,monospace}
th,td{padding:5px 9px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{background:var(--paper);color:var(--muted);font-weight:600;position:sticky;top:0}
td:first-child,th:first-child{text-align:left}
pre{background:var(--pre);color:var(--pre-ink);padding:12px;border-radius:6px;overflow:auto;
max-height:460px;font:12px/1.45 "JetBrains Mono",Consolas,monospace;white-space:pre}
img{max-width:100%;border:1px solid var(--line);border-radius:6px;background:#fff}
details{margin:8px 0}summary{cursor:pointer;color:var(--accent)}
.caption{color:var(--muted);font-size:13px;margin:4px 0 8px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px}
code{font:13px "JetBrains Mono",Consolas,monospace}
"""


def _img(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'<img alt="{escape(path.stem)}" src="data:image/png;base64,{data}">'


def _table(header: list, rows: list) -> str:
    head = "".join(f"<th>{escape(str(h))}</th>" for h in header)
    body = "".join(
        "<tr>" + "".join(f"<td>{'' if v is None else escape(str(v))}</td>" for v in r) + "</tr>"
        for r in rows
    )
    return f'<div class="scroll"><table><tr>{head}</tr>{body}</table></div>'


def _csv_table(path: Path) -> str:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    return _table(rows[0], rows[1:]) if rows else "<p>(empty)</p>"


def _snapshot(snap: dict) -> str:
    cols = ", ".join(
        f"{escape(n)} <span class='caption'>{escape(t)}</span>" for n, t in snap["columns"]
    )
    return (
        f"<h4><code>{escape(snap['table'])}</code> &middot; {snap['row_count']:,} rows</h4>"
        f"<p class='caption'>{cols}</p>" + _table([c[0] for c in snap["columns"]], snap["sample"])
    )


def _sprint(d: Path) -> str:
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    captions = meta.get("captions", {})
    parts = [
        f"<section class='sprint' id='{escape(d.name)}'>",
        f"<span class='tag'>{escape(d.name)}</span>"
        f"<span class='tag'>{escape(meta.get('pattern', ''))}</span>",
        f"<h2>{escape(meta['title'])}</h2><p class='sub'>{escape(meta['goal'])}</p>",
    ]
    if meta.get("findings"):
        parts.append(
            "<h3>What the run found</h3><ul class='findings'>"
            + "".join(f"<li>{escape(x)}</li>" for x in meta["findings"])
            + "</ul>"
        )
    for p in sorted((d / "metrics").glob("*.csv")):
        parts.append(
            f"<h3>{escape(captions.get(p.name, {}).get('title', p.stem))}</h3>"
            f"<p class='caption'>{escape(captions.get(p.name, {}).get('note', ''))}"
            f" Source: <code>results/{d.name}/metrics/{p.name}</code></p>{_csv_table(p)}"
        )
    charts = sorted((d / "charts").glob("*.png"))
    if charts:
        parts.append(
            "<h3>Charts</h3><div class='grid'>"
            + "".join(
                f"<figure>{_img(c)}<figcaption class='caption'>"
                f"{escape(captions.get(c.name, {}).get('title', c.stem))}</figcaption></figure>"
                for c in charts
            )
            + "</div>"
        )
    shots = sorted((d / "site").glob("*.png"))
    if shots:
        parts.append(
            "<h3>The site (screenshots from the running app)</h3><div class='grid'>"
            + "".join(
                f"<figure>{_img(c)}<figcaption class='caption'>{escape(c.stem)} tab</figcaption>"
                "</figure>"
                for c in shots
            )
            + "</div>"
        )
    if (d / "architecture.png").exists():
        parts.append("<h3>As-built architecture</h3>" + _img(d / "architecture.png"))
    if meta.get("commands"):
        parts.append("<h3>Commands</h3><pre>" + escape("\n".join(meta["commands"])) + "</pre>")
    if meta.get("scripts"):
        parts.append(
            "<h3>Scripts and SQL used</h3><ul>"
            + "".join(f"<li><code>{escape(s)}</code></li>" for s in meta["scripts"])
            + "</ul>"
        )
    snaps = sorted((d / "tables").glob("*.json"))
    if snaps:
        parts.append("<h3>Tables: raw (before) to marts (after)</h3>")
        order = meta.get("table_order", [])
        snaps.sort(key=lambda p: order.index(p.stem) if p.stem in order else len(order))
        parts += [_snapshot(json.loads(p.read_text(encoding="utf-8"))) for p in snaps]
    if (d / "review.md").exists():
        parts.append(
            "<h3>Ponytail review</h3><pre>"
            + escape((d / "review.md").read_text(encoding="utf-8"))
            + "</pre>"
        )
    outs = sorted((d / "run").glob("*.out"))
    if outs:
        parts.append("<h3>Terminal output (verbatim)</h3>")
        parts += [
            f"<details><summary>{escape(o.name)}</summary><pre>"
            f"{escape(o.read_text(encoding='utf-8'))}</pre></details>"
            for o in outs
        ]
    if meta.get("limits"):
        parts.append(
            "<h3>Known limits</h3><ul>"
            + "".join(f"<li>{escape(x)}</li>" for x in meta["limits"])
            + "</ul>"
        )
    parts.append("</section>")
    return "\n".join(parts)


def build_page(results_dir: Path) -> str:
    sprints = sorted(
        (p for p in Path(results_dir).iterdir() if (p / "meta.json").exists()),
        key=lambda p: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", p.name)],
        reverse=True,
    )
    body = "\n".join(_sprint(d) for d in sprints)
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Weatherwise sprint results</title><style>{CSS}</style></head><body><main>"
        "<h1>Weatherwise sprint results</h1>"
        "<p class='sub'>Generated by <code>scripts/build_results.py</code> from captured run "
        "files. Newest sprint first.</p>"
        f"{body}</main></body></html>"
    )
