# Lens. Offline LLMOps observability. Run `make help`.
PY ?= python3

.PHONY: help install up test eval gate gate-seeded demo dashboard interview lint typecheck ci clean

help:            ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

install:         ## Install runtime and dev dependencies
	$(PY) -m pip install -r requirements-dev.txt

up:              ## Serve the dashboard on http://127.0.0.1:8088
	$(PY) -m lens.cli serve --port $${LENS_PORT:-8088}

test:            ## Unit tests. No network, no API key.
	$(PY) -m pytest -q -W ignore::DeprecationWarning

eval:            ## Judge, drift, SLOs, both gates. Fails if the seeded regression is missed.
	$(PY) -m lens.cli eval

gate:            ## CI gate on the clean candidate. Exits 0.
	$(PY) -m lens.cli gate --candidate clean

gate-seeded:     ## CI gate on the seeded bad prompt. Exits 1.
	$(PY) -m lens.cli gate --candidate regressed

demo:            ## Print the offline walkthrough and refresh the dashboard
	$(PY) -m lens.cli demo

dashboard:       ## Regenerate the static dashboard HTML
	$(PY) -m lens.cli eval

interview:       ## Print the interview walkthrough
	bash scripts/interview_talk.sh

lint:            ## Ruff
	$(PY) -m ruff check lens tests
	$(PY) -m ruff format --check lens tests

typecheck:       ## mypy
	$(PY) -m mypy

format:          ## Auto-format
	$(PY) -m ruff format lens tests
	$(PY) -m ruff check --fix lens tests

ci: test eval    ## What CI runs, plus the workflow's explicit gate steps

clean:           ## Drop caches
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache
