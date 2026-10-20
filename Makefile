# Lookout: one-command setup, data build, run, evals, tests, scenarios.
# Reviewers: macOS or Linux, Python 3.11+, Node 20+. Two commands: `make setup` (installs and builds the data), then `make run`. Set ANTHROPIC_API_KEY (see .env.example) to run the agent live.

# The first Python 3.11+ on PATH (on macOS, plain python3 can be the system's 3.9).
PY ?= $(shell for p in python3.13 python3.12 python3.11 python3; do command -v $$p >/dev/null 2>&1 && $$p -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null && { echo $$p; break; }; done)
VENV := backend/.venv
PIP := $(VENV)/bin/pip
PYTHON := $(VENV)/bin/python

.DEFAULT_GOAL := help
.PHONY: help setup run ui build-data eval eval-docs eval-gate numbers check-ui test smoke-agent scenario scenarios hindsight perturbed clean api simulate-replies demo-state

help: ## list the targets
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/^([a-zA-Z_-]+):.*## (.*)/  make \1  -  \2/'

setup: $(VENV)/bin/activate ## install everything and build the data (the first of two commands: then `make run`)
	$(PIP) install -q -e 'backend[dev]'
	@if [ -f frontend/package.json ]; then cd frontend && npm install --silent; fi
	@$(MAKE) --no-print-directory build-data
	@echo "setup done. Next: make run"

$(VENV)/bin/activate:
	@if [ -z "$(PY)" ]; then echo "Lookout needs Python 3.11 or newer on PATH (python3.11, python3.12 or python3.13)."; exit 1; fi
	$(PY) -m venv $(VENV)
	$(PIP) install -q --upgrade pip

build-data: ## rebuild backend/lookout.db from data/ by replaying the approved recipe (no model, no key; never edits data/). AS_OF=2026-09-17 builds the database as the data stood that day
	cd backend && LOOKOUT_AS_OF=$(AS_OF) ../$(PYTHON) -m app.domain.imports.build --recipe ../recipes/halden

ui: ## build the UI only when it is missing or older than its sources
	@if [ -f frontend/package.json ] && { [ ! -d frontend/dist ] || [ -n "$$(find frontend/src frontend/index.html -newer frontend/dist -print -quit 2>/dev/null)" ]; }; then cd frontend && npm run build --silent; fi

run: ui ## serve the API and the built UI on http://127.0.0.1:8000 (builds the data first if the database is missing; AS_OF=... serves a database built with the same date)
	@if [ ! -f backend/lookout.db ]; then echo "no database yet: building the data first"; $(MAKE) --no-print-directory build-data; fi
	cd backend && LOOKOUT_AS_OF=$(AS_OF) ../$(PYTHON) -m uvicorn app.main:app --host 127.0.0.1 --port 8000

eval: ## the 15-case answer sheet and its report (ARGS="--full" runs every sheet; ARGS="--no-model" needs no key)
	$(PYTHON) -m evals.run $(ARGS)

eval-docs: ## after a run: re-render the report, the README block, the evals history and the one-screen page from the committed reports, in one step
	$(PYTHON) -m evals.run --rerender > /dev/null
	$(PYTHON) -m evals.readme_block --write
	$(PYTHON) -m evals.report_html

eval-gate: ## replays the shipped recordings through the graders (no key): tests the graders and the code, not the agent; fails if a case that passed in the committed report fails now
	$(PYTHON) -m evals.run --no-model --strict --gate --full

numbers: ## the number truth sweep: every figure the screens show, recomputed from data/ (not from the database); prints the mismatches (add ARGS=--all for every figure)
	$(PYTHON) -m evals.number_sweep $(ARGS)

check-ui: ## the UI checks: design-system tokens, no sideways scroll, keyboard focus (needs `make run` in another shell)
	cd frontend && BASE=http://127.0.0.1:8000 npm run check:ui

smoke-agent: ## stream one gated tool call through the organism on the installed Agent SDK
	cd backend && ../$(PYTHON) -m app.organism.dev.smoke

test: ## backend, eval and Watcher unit tests (no model, no key)
	@if [ -d backend/tests ] && [ -n "$$(find backend/tests -name 'test_*.py' -print -quit)" ]; then cd backend && ../$(PYTHON) -m pytest -q; fi
	$(PYTHON) -m pytest -q evals/tests

scenario: ## drive the running app end to end and record what happened (watcher/): S=fire|injection|fraud
	$(PYTHON) -m watcher.scenario $(S)

hindsight: ## build the records as they stood on four days of the month and check the Action list flags each thing the day it arrives, never before (no model, no key)
	$(PYTHON) -m evals.hindsight $(if $(JSON),--json evals/hindsight.json)

api: ## the API contract on the built database: every endpoint, every key the screens request, bad input is a clean 4xx (no model, no key)
	cd backend && .venv/bin/python -m pytest tests/domain/test_api_contract.py -q -p no:cacheprovider

perturbed: ## the recipe on changed data (a supplier renamed, another fraud amount): the Action list, trust and the oracle's tariff on numbers neither has seen (no model, no key)
	$(PYTHON) -m evals.perturbed $(if $(JSON),--json evals/perturbed.json)

tools: ## the tool contract: every tool through the real MCP server on the built data (valid, bad input, gate refusal); no model, no key
	cd backend && ../$(PYTHON) -m pytest -q tests/tools

tools-doc: ## regenerates evals/TOOLS-AND-WORKFLOWS.md from the tool registry, a test run and the saved live runs
	$(PYTHON) -m evals.tools_and_workflows

scenarios: ## the three system scenarios on a fresh app playing recordings (no key); each is read back from the Watcher
	$(PYTHON) -m watcher.scenario all --replay $(if $(JSON),--json evals/scenarios.json)

DEMO_ITEMS ?= disruption:SUP-0001,disruption:SUP-0013,incident:SUP-0018,tariff:all,consignment:HR-30110,risk:SUP-0029,risk:SUP-0002,deadline:chase,deadline:SUP-0041:2026-10-15,unknown:origin,unknown:stale-orders,deadline:quotes,unknown:hts,risk:SUP-0011,deadline:SUP-0016:2026-12-31,deadline:SUP-0042:2026-09-28,unknown:undated
demo-state: ## the interview's demo database, reproducibly: rebuild from data/, then replay the pinned cases' saved runs (no key; drafts wait for approval, nothing is sent). LOOKOUT_DB=<path> writes a copy instead of backend/lookout.db
	$(MAKE) build-data
	cd backend && LOOKOUT_MODE=recorded LOOKOUT_MORNING_ITEMS="$(DEMO_ITEMS)" ../$(PYTHON) -m app.organism.prepare

simulate-replies: ## demo only: write one simulated reply (marked as such) from the contact on file to every sent supplier request, so the item shows Answered and the Inbox lists it (no model, no key; writes backend/lookout.db, never data/)
	cd backend && ../$(PYTHON) -m app.domain.inbox.simulate_reply --all

clean:
	rm -rf $(VENV) backend/lookout.db frontend/node_modules frontend/dist
