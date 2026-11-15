PY := .venv/Scripts/python
S := .claude/skills/stack-diagram/scripts
SPRINT ?= sprint-04
CITY ?= torrance
TESTS ?= 184
MUTANTS ?= 52
# sprint-03 diagram: ARCH=scripts/make_arch_src.py SPRINT=sprint-03
ARCH ?= scripts/make_agent_arch_src.py
RUN := results/$(SPRINT)/run

.PHONY: setup up down migrate test check run site results diagram mutate agent prove-resume

setup:
	uv venv -p 3.11 .venv && uv pip install -p .venv --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match -e ".[dev]" && $(PY) -m playwright install chromium

up:
	docker compose up -d --wait

down:
	docker compose down

migrate:
	$(PY) -c "from weatherwise import warehouse; print(warehouse.migrate(warehouse.connect()) or 'up to date')"

test:
	$(PY) -m pytest -q -rA 2>&1 | tee $(RUN)/green.out

check:
	( $(PY) -m ruff check src tests scripts && $(PY) -m ruff format --check src tests scripts && $(PY) -m sqlfluff lint sql ) 2>&1 | tee $(RUN)/check.out

run:
	PYTHONIOENCODING=utf-8 $(PY) -u scripts/run_pipeline.py --city $(CITY) --sprint $(SPRINT) 2>&1 | tee $(RUN)/pipeline.out

diagram:
	$(PY) $(ARCH) $(TESTS) $(MUTANTS)
	$(PY) $(S)/build.py results/$(SPRINT)/arch.src.html .stack-icons results/$(SPRINT)/architecture.html --fonts .claude/skills/stack-diagram/assets/fonts
	$(PY) $(S)/render_png.py results/$(SPRINT)/architecture.html results/$(SPRINT)/architecture.png --selector .canvas --scale 2

site:
	$(PY) scripts/run_site.py

results:
	$(PY) scripts/build_results.py
	$(PY) $(S)/render_png.py results/index.html results/index.png --full-page --single --scale 1

agent:
	$(PY) scripts/run_agent.py "$(Q)"

prove-resume:
	$(PY) scripts/prove_resume.py 2>&1 | tee $(RUN)/resume.out

mutate:
	$(PY) scripts/mutation_check.py 2>&1 | tee $(RUN)/mutation.out
