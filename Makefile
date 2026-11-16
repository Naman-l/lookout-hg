# Lookout: one-command setup, data build, run, evals, tests, scenarios.
# Reviewers: macOS or Linux, Python 3.12+, Node 20+. Two commands: `make setup` (installs, writes the dummy data if data/ is missing, builds the database), then `make run`.
# Set ANTHROPIC_API_KEY (see .env.example) to run the agent live.

# The first Python 3.12+ on PATH (the backend uses PEP 701 f-strings; on macOS, plain python3 can be the system's 3.9).
PY ?= $(shell for p in python3.14 python3.13 python3.12 python3; do command -v $$p >/dev/null 2>&1 && $$p -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null && { echo $$p; break; }; done)
# The port the app serves on, and the recipe the build replays (recipes/DEFAULT names it; RECIPE=recipes/<name> overrides).
PORT ?= 8001
THEN ?= 2026-09-01
RECIPE ?= recipes/$(shell cat recipes/DEFAULT 2>/dev/null)
VENV := backend/.venv
PIP := $(VENV)/bin/pip
PYTHON := $(VENV)/bin/python

.DEFAULT_GOAL := help
.PHONY: help setup data run ui build-data check-ui test numbers hindsight then scenarios demo-state clean simulate-replies

help: ## list the targets
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/^([a-zA-Z_-]+):.*## (.*)/  make \1  -  \2/'

setup: $(VENV)/bin/activate ## install everything and build the data (the first of two commands: then `make run`)
	$(PIP) install -q -e 'backend[dev]'
	@if [ -f frontend/package.json ]; then cd frontend && npm install --silent; fi
	@if [ ! -d data ]; then $(MAKE) --no-print-directory data; fi
	@$(MAKE) --no-print-directory build-data
	@echo "setup done. Next: make run"

$(VENV)/bin/activate:
	@if [ -z "$(PY)" ]; then echo "Lookout needs Python 3.12 or newer on PATH (python3.12, python3.13 or python3.14)."; exit 1; fi
	$(PY) -m venv $(VENV)
	$(PIP) install -q --upgrade pip

data: ## write the dummy dataset into data/ (fixed seed: the same files every time; wipes and rewrites data/)
	$(PYTHON) dummy_data/generate_hg.py

build-data: ## rebuild backend/lookout.db from data/ by replaying the approved recipe (no model, no key; never edits data/). AS_OF=2026-09-01 builds the database as the data stood that day
	cd backend && LOOKOUT_AS_OF=$(AS_OF) ../$(PYTHON) -m app.domain.imports.build --recipe ../$(RECIPE)

ui: ## build the UI only when it is missing or older than its sources
	@if [ -f frontend/package.json ] && { [ ! -d frontend/dist ] || [ -n "$$(find frontend/src frontend/index.html -newer frontend/dist -print -quit 2>/dev/null)" ]; }; then cd frontend && npm run build --silent; fi

run: ui ## serve the API and the built UI on http://127.0.0.1:$(PORT) (builds the data first if the database is missing; AS_OF=... serves a database built with the same date)
	@if [ ! -f backend/lookout.db ]; then echo "no database yet: building the data first"; $(MAKE) --no-print-directory build-data; fi
	cd backend && LOOKOUT_AS_OF=$(AS_OF) ../$(PYTHON) -m uvicorn app.main:app --host 127.0.0.1 --port $(PORT)

check-ui: ## the UI checks: design-system tokens, no sideways scroll, keyboard focus (needs `make run` in another shell)
	cd frontend && BASE=http://127.0.0.1:$(PORT) npm run check:ui

numbers: ## the number check: every figure the API serves for the screens against a pandas oracle over data/ (needs `make run`)
	$(PYTHON) -I evals/number_check.py

hindsight: ## rebuild the records as they stood on 1 Sep, 1 Oct, 14 Oct and 20 Oct: each case appears the day its evidence arrives, never before
	$(PYTHON) evals/hindsight.py

then: ui ## serve the records as they stood on a past day (THEN=2026-09-01) on http://127.0.0.1:8002, beside today's on :8001: the demo's hindsight moment
	cd backend && LOOKOUT_AS_OF=$(THEN) ../$(PYTHON) -m app.domain.imports.build --recipe ../$(RECIPE) --db lookout-$(THEN).db
	cd backend && LOOKOUT_AS_OF=$(THEN) LOOKOUT_DB=backend/lookout-$(THEN).db ../$(PYTHON) -m uvicorn app.main:app --host 127.0.0.1 --port 8002

scenarios: ## the end-to-end stories on a copy of the database: the MFC case signed and countersigned, the cement injection held, the bank-change fraud held
	$(PYTHON) evals/scenarios.py

demo-state: ## reset the demo: rebuild the database from data/ (no ledger, no runs); `make run` then replays the recordings and works every case by code
	rm -f backend/lookout.db backend/lookout.db-shm backend/lookout.db-wal
	@$(MAKE) --no-print-directory build-data

test: ## backend unit tests (no model, no key)
	@if [ -d backend/tests ] && [ -n "$$(find backend/tests -name 'test_*.py' -print -quit)" ]; then cd backend && ../$(PYTHON) -m pytest -q; fi

simulate-replies: ## demo only: write one simulated reply (marked as such) from the contact on file to every sent request, so the item shows Answered and the Inbox lists it (no model, no key; writes backend/lookout.db, never data/)
	cd backend && ../$(PYTHON) -m app.domain.inbox.simulate_reply --all

clean:
	rm -rf $(VENV) backend/lookout.db frontend/node_modules frontend/dist
