# Conduit. Offline embedding CDC. Run `make help`.
PY ?= python3

.PHONY: help install up test eval demo interview lint typecheck format ci clean

help:            ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

install:         ## Install runtime and dev dependencies
	$(PY) -m pip install -r requirements-dev.txt

up:              ## Serve the demo UI on http://127.0.0.1:8097
	$(PY) -m conduit.cli serve --port $${CONDUIT_PORT:-8097}

test:            ## Unit tests. No network, no API key.
	$(PY) -m pytest -q -W ignore::DeprecationWarning

eval:            ## Migration, RTBF, recall, latency, cost projection. Writes reports/eval.json.
	$(PY) -m conduit.cli eval

demo:            ## Run the offline story in the terminal
	$(PY) -m conduit.cli demo

interview:       ## Print the interview walkthrough
	$(PY) -m conduit.cli interview

lint:            ## Ruff
	$(PY) -m ruff check conduit tests
	$(PY) -m ruff format --check conduit tests

typecheck:       ## mypy
	$(PY) -m mypy

format:          ## Auto-format
	$(PY) -m ruff format conduit tests
	$(PY) -m ruff check --fix conduit tests

ci: lint typecheck test eval   ## What CI runs

clean:           ## Drop caches and the local database
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache var
