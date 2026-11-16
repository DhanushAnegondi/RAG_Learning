"""Write results/sprint-05/arch.src.html: the daily run as built. Theme from the sprint-01
diagram; counts from results/sprint-05 (scripts/write_ops_results.py).

Run: .venv/Scripts/python scripts/make_ops_arch_src.py TESTS MUTANTS; then make diagram.
"""

import csv
import json
import pathlib
import shutil
import sys

root = pathlib.Path(".")
out = root / "results/sprint-05"
src = (root / "results/sprint-01/arch.src.html").read_text(encoding="utf-8")
head = src[: src.index("<body>")].replace("sprint-01 as-built", "sprint-05 as-built")
body = """<body>
<div class="page">

  <header class="head">
    <div>
      <div class="kicker">weatherwise / sprint-05 / as-built 2026-11-15</div>
      <h1>The daily run: forecast with the stored methods, stop for a person on drift</h1>
    </div>
    <p class="lede">Five steps, one at a time, each saved to Postgres. The run does not re-choose its methods; it measures whether they still work, and if they do not it waits for a decision before retraining. Every run ends in a stated state in the run log.</p>
  </header>

  <div class="scroller">
  <div class="canvas">

    <div class="group ga" style="left:182px; top:150px; width:800px; height:150px;">
      <div class="g-label"><img src="%%ICON_python%%" alt="">LangGraph run graph (ops.py), one run at a time</div>
    </div>
    <div class="group gb" style="left:182px; top:380px; width:800px; height:190px;">
      <div class="g-label" style="top:auto; bottom:12px;"><img src="%%ICON_postgresql%%" alt="">Postgres 18 in Docker</div>
    </div>

    <svg class="edges" viewBox="0 0 1000 600" aria-hidden="true">
      <defs>
        <marker id="ar" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" fill="context-stroke"/>
        </marker>
      </defs>
      <path class="e" d="M146 230 H238" marker-end="url(#ar)"/>
      <text class="el a" x="192" y="222" text-anchor="middle">APIs</text>
      <path class="e" d="M306 230 H398" marker-end="url(#ar)"/>
      <path class="e" d="M466 230 H558" marker-end="url(#ar)"/>
      <text class="el a" x="512" y="222" text-anchor="middle">drift?</text>
      <path class="e" d="M626 230 H718" marker-end="url(#ar)"/>
      <path class="e" d="M786 230 H878" marker-end="url(#ar)"/>
      <path class="n dash" d="M592 196 V136" marker-end="url(#ar)" marker-start="url(#ar)"/>
      <text class="el" x="604" y="172">approve / decline</text>
      <path class="e" d="M272 304 V416" marker-end="url(#ar)"/>
      <text class="el a" x="282" y="366">load</text>
      <path class="e" d="M432 304 V416" marker-end="url(#ar)" marker-start="url(#ar)"/>
      <text class="el a" x="442" y="366">recent vs stored</text>
      <path class="e" d="M592 304 V416" marker-end="url(#ar)" marker-start="url(#ar)"/>
      <text class="el a" x="602" y="366">waits here</text>
      <path class="e" d="M752 304 V416" marker-end="url(#ar)"/>
      <text class="el a" x="762" y="366">today's forecast</text>
      <path class="e" d="M912 304 V416" marker-end="url(#ar)"/>
      <text class="el a" x="922" y="366">state</text>
    </svg>

    <div class="node" style="left:46px;top:200px">
      <div class="tile"><img src="%%ICON_cloud%%" alt=""></div>
      <div class="name"><span>Open-Meteo</span></div><div class="role"><span>3 APIs</span></div>
    </div>
    <div class="node" style="left:526px;top:30px">
      <div class="tile"><img src="%%ICON_user%%" alt=""></div>
      <div class="name"><span>You</span></div><div class="role"><span>only on drift</span></div>
    </div>
    <div class="node" style="left:206px;top:200px">
      <div class="tile"><img src="%%ICON_python%%" alt=""></div>
      <div class="name"><span>fetch</span></div><div class="role"><span>new data</span></div>
    </div>
    <div class="node" style="left:366px;top:200px">
      <div class="tile"><img src="%%ICON_python%%" alt=""></div>
      <div class="name"><span>check</span></div><div class="role"><span>lag, hole, drift</span></div>
    </div>
    <div class="node" style="left:526px;top:200px">
      <div class="tile"><img src="%%ICON_python%%" alt=""></div>
      <div class="name"><span>gate</span></div><div class="role"><span>interrupt</span></div>
    </div>
    <div class="node" style="left:686px;top:200px">
      <div class="tile"><img src="%%ICON_sklearn%%" alt=""></div>
      <div class="name"><span>forecast</span></div><div class="role"><span>stored methods</span></div>
    </div>
    <div class="node" style="left:846px;top:200px">
      <div class="tile"><img src="%%ICON_python%%" alt=""></div>
      <div class="name"><span>finish</span></div><div class="role"><span>mark ok</span></div>
    </div>
    <div class="node" style="left:206px;top:420px">
      <div class="tile"><img src="%%ICON_db%%" alt=""></div>
      <div class="name"><span>raw + marts</span></div><div class="role"><span>rebuilt</span></div>
    </div>
    <div class="node" style="left:366px;top:420px">
      <div class="tile"><img src="%%ICON_db%%" alt=""></div>
      <div class="name"><span>app_model_eval</span></div><div class="role"><span>DRIFTED of PAIRS drifted</span></div>
    </div>
    <div class="node" style="left:526px;top:420px">
      <div class="tile"><img src="%%ICON_db%%" alt=""></div>
      <div class="name"><span>checkpoints</span></div><div class="role"><span>per step</span></div>
    </div>
    <div class="node" style="left:686px;top:420px">
      <div class="tile"><img src="%%ICON_db%%" alt=""></div>
      <div class="name"><span>log_forecast</span></div><div class="role"><span>live, write once</span></div>
    </div>
    <div class="node" style="left:846px;top:420px">
      <div class="tile"><img src="%%ICON_db%%" alt=""></div>
      <div class="name"><span>app_run_log</span></div><div class="role"><span>runs: RUNS</span></div>
    </div>

  </div>
  </div>

  <div class="legend">
    <span><span class="sw"></span>data and state</span>
    <span><span class="sw n dash"></span>a person's decision, only when drift is found</span>
  </div>

  <div class="foot">
    <span>weatherwise sprint-05, counts from results/sprint-05; TESTS tests, MUTANTS sprint-05 mutants</span>
    <span>icons: svgl / devicon / Lucide / scikit-learn repo · made with <a href="https://github.com/caru-ini/stack-diagram" target="_blank" rel="noopener">stack-diagram</a></span>
  </div>

</div>
</body>
</html>
"""
runs = json.loads((out / "tables/app_run_log.json").read_text(encoding="utf-8"))["row_count"]
with (out / "metrics/02_drift_check.csv").open(encoding="utf-8", newline="") as f:
    pairs = list(csv.DictReader(f))
drifted = sum(r["drifted"] == "True" for r in pairs)
body = body.replace("DRIFTED", str(drifted)).replace("PAIRS", str(len(pairs)))
body = body.replace("RUNS", str(runs))
body = body.replace("TESTS", sys.argv[1]).replace("MUTANTS", sys.argv[2])
(out / "arch.src.html").write_text(head + body, encoding="utf-8", newline="\n")
icons = root / ".stack-icons"
shutil.copy(root / ".claude/skills/stack-diagram/assets/generic/user.svg", icons / "user.svg")
print("diagram source written", runs, drifted, len(pairs))
