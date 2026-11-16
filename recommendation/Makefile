SHELL := bash
.SHELLFLAGS := -o pipefail -c

PY := .venv/Scripts/python
S := .claude/skills/stack-diagram/scripts
SPRINT ?= sprint-01
RUN := results/$(SPRINT)/run

.PHONY: setup fetch test check run results diagram mutate recommend

setup:
	uv venv -p 3.11 .venv && uv pip install -p .venv -e ".[dev]" && $(PY) -m playwright install chromium

fetch:
	$(PY) -u scripts/fetch_data.py 2>&1 | tee $(RUN)/fetch.out

test:
	$(PY) -m pytest -rA -q -o addopts= 2>&1 | tee $(RUN)/green.out

check:
	( $(PY) -m ruff check src tests scripts && $(PY) -m ruff format --check src tests scripts && $(PY) -m sqlfluff lint sql ) 2>&1 | tee $(RUN)/check.out

run:
	PYTHONIOENCODING=utf-8 $(PY) -u scripts/run_pipeline.py --sprint $(SPRINT) 2>&1 | tee $(RUN)/pipeline.out

diagram:
	$(PY) scripts/build_diagram.py $(SPRINT)
	$(PY) $(S)/build.py results/$(SPRINT)/arch.src.html .stack-icons results/$(SPRINT)/architecture.html --fonts .claude/skills/stack-diagram/assets/fonts
	$(PY) $(S)/render_png.py results/$(SPRINT)/architecture.html results/$(SPRINT)/architecture.png --selector .canvas --scale 2

results:
	$(PY) scripts/build_results.py
	$(PY) $(S)/render_png.py results/index.html results/index.png --full-page --single --scale 1

mutate:
	$(PY) scripts/mutation_check.py 2>&1 | tee $(RUN)/mutation.out

# make recommend LIKE="Inception" LANG=te
recommend:
	PYTHONIOENCODING=utf-8 $(PY) scripts/recommend.py --like "$(LIKE)" --lang $(LANG)
