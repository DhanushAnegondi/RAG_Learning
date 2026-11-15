"""Write results/sprint-03/arch.src.html: sprint-01 theme, sprint-03 body, row counts from
table snapshots. Icons: fetch_icons.py .stack-icons postgresql (see the stack-diagram skill).

Run: .venv/Scripts/python scripts/make_arch_src.py TESTS MUTANTS; then make diagram.
"""

import json
import pathlib
import shutil
import sys

root = pathlib.Path(".")
src = (root / "results/sprint-01/arch.src.html").read_text(encoding="utf-8")
head = src[: src.index("<body>")].replace("sprint-01 as-built", "sprint-03 as-built")
body = """<body>
<div class="page">

  <header class="head">
    <div>
      <div class="kicker">weatherwise / sprint-03 / as-built 2026-11-14</div>
      <h1>Multi-model forecast, forecast log and the check-a-day site</h1>
    </div>
    <p class="lede">Four weather models land in Postgres, SQL cleans and pairs them with what happened, Python picks the best correction per lead, every forecast is logged, and the site compares the log with what you saw.</p>
  </header>

  <div class="scroller">
  <div class="canvas">

    <div class="group ga" style="left:22px; top:30px; width:180px; height:400px;">
      <div class="g-label"><img src="%%ICON_cloud%%" alt="">Open-Meteo</div>
    </div>
    <div class="group gb" style="left:442px; top:140px; width:500px; height:400px;">
      <div class="g-label"><img src="%%ICON_postgresql%%" alt="">Postgres 18 in Docker</div>
    </div>

    <svg class="edges" viewBox="0 0 1000 600" aria-hidden="true">
      <defs>
        <marker id="ar" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" fill="context-stroke"/>
        </marker>
      </defs>
      <path class="e" d="M148 100 H322 V196" marker-end="url(#ar)"/>
      <text class="el a" x="235" y="92" text-anchor="middle">actuals</text>
      <path class="e" d="M148 230 H286" marker-end="url(#ar)"/>
      <text class="el a" x="218" y="222" text-anchor="middle">4 models</text>
      <path class="e" d="M148 350 H322 V268" marker-end="url(#ar)"/>
      <text class="el a" x="235" y="342" text-anchor="middle">live</text>
      <path class="e" d="M358 230 H496" marker-end="url(#ar)"/>
      <text class="el a" x="400" y="222" text-anchor="middle">upsert</text>
      <path class="e" d="M568 230 H656" marker-end="url(#ar)"/>
      <text class="el a" x="612" y="222" text-anchor="middle">clean</text>
      <path class="e" d="M728 230 H816" marker-end="url(#ar)"/>
      <text class="el a" x="772" y="222" text-anchor="middle">pair</text>
      <path class="e" d="M852 304 V416" marker-end="url(#ar)"/>
      <text class="el a" x="862" y="366">train</text>
      <path class="e" d="M816 450 H728" marker-end="url(#ar)"/>
      <text class="el a" x="772" y="442" text-anchor="middle">forecasts</text>
      <path class="e" d="M656 450 H568" marker-end="url(#ar)"/>
      <text class="el a" x="612" y="442" text-anchor="middle">compare</text>
      <path class="e" d="M496 450 H358" marker-end="url(#ar)"/>
      <text class="el a" x="412" y="442" text-anchor="middle">sql/site</text>
      <path class="n" d="M286 462 H148" marker-end="url(#ar)" marker-start="url(#ar)"/>
      <text class="el" x="218" y="482" text-anchor="middle">page / entry</text>
      <path class="n dash" d="M344 420 V378 H508 V304" marker-end="url(#ar)"/>
      <text class="el" x="426" y="370" text-anchor="middle">what you saw</text>
    </svg>

    <div class="node" style="left:46px;top:70px">
      <div class="tile"><img src="%%ICON_archive%%" alt=""></div>
      <div class="name"><span>ERA5 archive</span></div><div class="role"><span>actuals 1995-2026</span></div>
    </div>
    <div class="node" style="left:46px;top:200px">
      <div class="tile"><img src="%%ICON_prevruns%%" alt=""></div>
      <div class="name"><span>Previous runs</span></div><div class="role"><span>4 models, lead 1-7</span></div>
    </div>
    <div class="node" style="left:46px;top:320px">
      <div class="tile"><img src="%%ICON_forecast%%" alt=""></div>
      <div class="name"><span>Forecast API</span></div><div class="role"><span>live, 16 days</span></div>
    </div>
    <div class="node" style="left:256px;top:200px">
      <div class="tile"><img src="%%ICON_python%%" alt=""></div>
      <div class="name"><span>ingest.py</span></div><div class="role"><span>retry + parse</span></div>
    </div>
    <div class="node" style="left:466px;top:200px">
      <div class="tile"><img src="%%ICON_db%%" alt=""></div>
      <div class="name"><span>raw_*</span></div><div class="role"><span>RAW_ROWS</span></div>
    </div>
    <div class="node" style="left:626px;top:200px">
      <div class="tile"><img src="%%ICON_db%%" alt=""></div>
      <div class="name"><span>stg_*</span></div><div class="role"><span>cleaning rules</span></div>
    </div>
    <div class="node" style="left:786px;top:200px">
      <div class="tile"><img src="%%ICON_db%%" alt=""></div>
      <div class="name"><span>mart_model_pairs</span></div><div class="role"><span>PAIR_ROWS</span></div>
    </div>
    <div class="node" style="left:786px;top:420px">
      <div class="tile wide"><img src="%%ICON_sklearn%%" alt=""></div>
      <div class="name"><span>models.py + deep.py</span></div><div class="role"><span>blend, drift, LSTM</span></div>
    </div>
    <div class="node" style="left:626px;top:420px">
      <div class="tile"><img src="%%ICON_db%%" alt=""></div>
      <div class="name"><span>log_forecast</span></div><div class="role"><span>LOG_ROWS</span></div>
    </div>
    <div class="node" style="left:466px;top:420px">
      <div class="tile"><img src="%%ICON_db%%" alt=""></div>
      <div class="name"><span>mart_verification</span></div><div class="role"><span>forecast vs entry</span></div>
    </div>
    <div class="node" style="left:256px;top:420px">
      <div class="tile"><img src="%%ICON_python%%" alt=""></div>
      <div class="name"><span>site.py</span></div><div class="role"><span>FastAPI + web/</span></div>
    </div>
    <div class="node" style="left:46px;top:440px">
      <div class="tile"><img src="%%ICON_user%%" alt=""></div>
      <div class="name"><span>You</span></div><div class="role"><span>localhost:8000</span></div>
    </div>

  </div>
  </div>

  <div class="legend">
    <span><span class="sw"></span>data flow</span>
    <span><span class="sw n"></span>site traffic</span>
    <span><span class="sw n dash"></span>your entries, stored in raw_user_observation</span>
  </div>

  <div class="foot">
    <span>weatherwise sprint-02, row counts from results/sprint-03/tables/*.json; TESTS tests, MUTANTS mutants</span>
    <span>icons: svgl / devicon / Lucide / scikit-learn repo · made with <a href="https://github.com/caru-ini/stack-diagram" target="_blank" rel="noopener">stack-diagram</a></span>
  </div>

</div>
</body>
</html>
"""
tables = root / "results/sprint-03/tables"


def count(t: str) -> int:
    return json.loads((tables / f"{t}.json").read_text(encoding="utf-8"))["row_count"]


raw = sum(count(t) for t in ("raw_actual_daily", "raw_published_hourly", "raw_live_forecast"))
body = body.replace("RAW_ROWS", f"{raw / 1000:.0f}k rows")
body = body.replace("PAIR_ROWS", f"{count('mart_model_pairs'):,} rows")
body = body.replace("LOG_ROWS", f"{count('log_forecast'):,} forecasts")
body = body.replace("TESTS", sys.argv[1]).replace("MUTANTS", sys.argv[2])
(root / "results/sprint-03/arch.src.html").write_text(head + body, encoding="utf-8", newline="\n")
icons = root / ".stack-icons"
shutil.copy(root / ".claude/skills/stack-diagram/assets/generic/user.svg", icons / "user.svg")
print("diagram source written", raw, count("mart_model_pairs"), count("log_forecast"))
