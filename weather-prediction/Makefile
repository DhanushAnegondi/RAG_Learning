PY := .venv/Scripts/python
S := .claude/skills/stack-diagram/scripts
SPRINT ?= sprint-01
RUN := results/$(SPRINT)/run

.PHONY: setup test check run results diagram mutate

setup:
	uv venv -p 3.11 .venv && uv pip install -p .venv -e ".[dev]" && $(PY) -m playwright install chromium

test:
	$(PY) -m pytest -q -rA 2>&1 | tee $(RUN)/green.out

check:
	( $(PY) -m ruff check src tests scripts && $(PY) -m ruff format --check src tests scripts && $(PY) -m sqlfluff lint sql ) 2>&1 | tee $(RUN)/check.out

run:
	PYTHONIOENCODING=utf-8 $(PY) -u scripts/run_pipeline.py --sprint $(SPRINT) 2>&1 | tee $(RUN)/pipeline.out

diagram:
	$(PY) $(S)/build.py results/$(SPRINT)/arch.src.html .stack-icons results/$(SPRINT)/architecture.html --fonts .claude/skills/stack-diagram/assets/fonts
	$(PY) $(S)/render_png.py results/$(SPRINT)/architecture.html results/$(SPRINT)/architecture.png --selector .canvas --scale 2

results:
	$(PY) scripts/build_results.py
	$(PY) $(S)/render_png.py results/index.html results/index.png --full-page --single --scale 1

mutate:
	$(PY) scripts/mutation_check.py 2>&1 | tee $(RUN)/mutation.out
