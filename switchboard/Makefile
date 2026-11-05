# Switchboard model router. Run `make help`.
PY ?= .venv/bin/python

.PHONY: help install test demo eval bench run-local interview up down lint capture clean

help:            ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

install:         ## Create .venv and install runtime + test dependencies
	python3 -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

test:            ## Unit + integration tests
	$(PY) -m pytest

demo:            ## Route the locked scenarios and print PASS/FAIL
	$(PY) scripts/demo.py

eval:            ## Corpus eval -> reports/eval.md
	$(PY) eval/run_eval.py

bench:           ## In-process router overhead -> reports/latency.md
	$(PY) bench/latency.py

run-local:       ## API and demo UI on :8092
	$(PY) -m switchboard

interview:       ## Print the interview talk track
	./scripts/interview_talk.sh

up:              ## Build and start the API container
	docker compose up --build -d

down:            ## Stop the API container
	docker compose down

lint:            ## Ruff lint and format check
	$(PY) -m ruff check switchboard tests eval bench scripts
	$(PY) -m ruff format --check switchboard tests eval bench scripts

capture:         ## Headless screenshots and a short silent demo video
	node scripts/capture_ui.mjs

clean:           ## Remove the local SQLite file and caches
	rm -f switchboard.db
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
