"""Write results/sprint-04/arch.src.html: the planning assistant as built. Theme from the
sprint-01 diagram; counts from results/sprint-04/tables/*.json (scripts/write_agent_results.py).

Run: .venv/Scripts/python scripts/make_agent_arch_src.py TESTS MUTANTS; then make diagram.
"""

import json
import pathlib
import shutil
import sys

root = pathlib.Path(".")
out = root / "results/sprint-04"
src = (root / "results/sprint-01/arch.src.html").read_text(encoding="utf-8")
head = src[: src.index("<body>")].replace("sprint-01 as-built", "sprint-04 as-built")
body = """<body>
<div class="page">

  <header class="head">
    <div>
      <div class="kicker">weatherwise / sprint-04 / as-built 2026-11-15</div>
      <h1>The planning assistant: a LangGraph loop over read-only tools</h1>
    </div>
    <p class="lede">A question goes through four steps. The model may only call fixed, typed queries that run as a read-only database role. Every step is saved, every tool call is logged, and an answer with a number the data does not hold is rewritten once, then refused.</p>
  </header>

  <div class="scroller">
  <div class="canvas">

    <div class="group ga" style="left:182px; top:150px; width:620px; height:150px;">
      <div class="g-label"><img src="%%ICON_python%%" alt="">LangGraph StateGraph (agent/graph.py)</div>
    </div>
    <div class="group gb" style="left:342px; top:380px; width:640px; height:190px;">
      <div class="g-label"><img src="%%ICON_postgresql%%" alt="">Postgres 18 in Docker</div>
    </div>

    <svg class="edges" viewBox="0 0 1000 600" aria-hidden="true">
      <defs>
        <marker id="ar" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" fill="context-stroke"/>
        </marker>
      </defs>
      <path class="n" d="M146 230 H238" marker-end="url(#ar)" marker-start="url(#ar)"/>
      <text class="el" x="192" y="222" text-anchor="middle">ask</text>
      <path class="e" d="M306 230 H398" marker-end="url(#ar)"/>
      <text class="el a" x="352" y="222" text-anchor="middle">question</text>
      <path class="e" d="M466 230 H558" marker-end="url(#ar)" marker-start="url(#ar)"/>
      <text class="el a" x="512" y="222" text-anchor="middle">tool calls</text>
      <path class="e" d="M417 196 V60 H306" marker-end="url(#ar)" marker-start="url(#ar)"/>
      <text class="el a" x="427" y="100">Messages API</text>
      <path class="e" d="M452 196 V186 H742 V196" marker-end="url(#ar)"/>
      <text class="el a" x="660" y="181" text-anchor="middle">draft answer</text>
      <path class="n dash" d="M762 196 V130 H434 V196" marker-end="url(#ar)"/>
      <text class="el" x="610" y="122" text-anchor="middle">invented number: one rewrite, then refuse</text>
      <path class="e" d="M238 245 H215 V450 H398" marker-end="url(#ar)" marker-start="url(#ar)"/>
      <text class="el a" x="225" y="366">preferences</text>
      <path class="e" d="M592 304 V416" marker-end="url(#ar)" marker-start="url(#ar)"/>
      <text class="el a" x="582" y="366" text-anchor="end">log + replay</text>
      <path class="e" d="M626 245 H660 V450 H718" marker-end="url(#ar)"/>
      <text class="el a" x="670" y="366">reader role, 10 s</text>
      <path class="e" d="M806 230 H912 V416" marker-end="url(#ar)" marker-start="url(#ar)"/>
      <text class="el a" x="922" y="320">state,</text>
      <text class="el a" x="922" y="336">every step</text>
    </svg>

    <div class="node" style="left:46px;top:200px">
      <div class="tile"><img src="%%ICON_user%%" alt=""></div>
      <div class="name"><span>You</span></div><div class="role"><span>Ask tab / make agent</span></div>
    </div>
    <div class="node" style="left:206px;top:30px">
      <div class="tile"><img src="%%ICON_cloud%%" alt=""></div>
      <div class="name"><span>Claude</span></div><div class="role"><span>MODEL</span></div>
    </div>
    <div class="node" style="left:206px;top:200px">
      <div class="tile"><img src="%%ICON_python%%" alt=""></div>
      <div class="name"><span>route</span></div><div class="role"><span>load preferences</span></div>
    </div>
    <div class="node" style="left:366px;top:200px">
      <div class="tile"><img src="%%ICON_python%%" alt=""></div>
      <div class="name"><span>model</span></div><div class="role"><span>limit CALLS calls</span></div>
    </div>
    <div class="node" style="left:526px;top:200px">
      <div class="tile"><img src="%%ICON_python%%" alt=""></div>
      <div class="name"><span>tools</span></div><div class="role"><span>NTOOLS typed tools</span></div>
    </div>
    <div class="node" style="left:686px;top:200px">
      <div class="tile"><img src="%%ICON_python%%" alt=""></div>
      <div class="name"><span>answer check</span></div><div class="role"><span>grounding.py</span></div>
    </div>
    <div class="node" style="left:366px;top:420px">
      <div class="tile"><img src="%%ICON_db%%" alt=""></div>
      <div class="name"><span>agent.store</span></div><div class="role"><span>per user</span></div>
    </div>
    <div class="node" style="left:526px;top:420px">
      <div class="tile"><img src="%%ICON_db%%" alt=""></div>
      <div class="name"><span>agent.tool_call</span></div><div class="role"><span>CALL_ROWS calls</span></div>
    </div>
    <div class="node" style="left:686px;top:420px">
      <div class="tile"><img src="%%ICON_db%%" alt=""></div>
      <div class="name"><span>marts + log</span></div><div class="role"><span>select only</span></div>
    </div>
    <div class="node" style="left:846px;top:420px">
      <div class="tile"><img src="%%ICON_db%%" alt=""></div>
      <div class="name"><span>agent.checkpoints</span></div><div class="role"><span>CKPT_ROWS rows</span></div>
    </div>

  </div>
  </div>

  <div class="legend">
    <span><span class="sw"></span>calls and data</span>
    <span><span class="sw n"></span>the conversation</span>
    <span><span class="sw n dash"></span>the number check sending a draft back</span>
  </div>

  <div class="foot">
    <span>weatherwise sprint-04, counts from results/sprint-04/tables/*.json; TESTS tests, MUTANTS sprint-04 mutants</span>
    <span>icons: svgl / devicon / Lucide · made with <a href="https://github.com/caru-ini/stack-diagram" target="_blank" rel="noopener">stack-diagram</a></span>
  </div>

</div>
</body>
</html>
"""


def count(t: str) -> int:
    return json.loads((out / "tables" / f"{t}.json").read_text(encoding="utf-8"))["row_count"]


sys.path.insert(0, str(root / "src"))
from weatherwise.agent import graph, tools  # noqa: E402

body = body.replace("CKPT_ROWS", f"{count('checkpoints'):,}")
body = body.replace("CALL_ROWS", f"{count('tool_call'):,}")
body = body.replace("NTOOLS", str(len(tools.TOOLS))).replace("MODEL", graph.DEFAULT_MODEL)
body = body.replace("CALLS", str(graph.MAX_MODEL_CALLS))
body = body.replace("TESTS", sys.argv[1]).replace("MUTANTS", sys.argv[2])
(out / "arch.src.html").write_text(head + body, encoding="utf-8", newline="\n")
icons = root / ".stack-icons"
shutil.copy(root / ".claude/skills/stack-diagram/assets/generic/user.svg", icons / "user.svg")
print("diagram source written", count("checkpoints"), count("tool_call"))
