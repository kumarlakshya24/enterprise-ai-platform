# Arena decision bench. Run `make help`.
PY ?= .venv/bin/python

.PHONY: help install up test eval demo gate interview lint run-local capture clean

help:            ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

install:         ## Create .venv and install runtime + test dependencies
	python3 -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

up:              ## Demo UI on http://127.0.0.1:8097
	$(PY) -m arena

run-local: up    ## Alias for make up

test:            ## Unit + integration tests. No network, no API key.
	$(PY) -m pytest

eval:            ## Fresh quality, cost, and overhead -> reports/latest.json
	$(PY) -m arena.cli eval

demo:            ## Locked scenarios and the four-arm refund check
	$(PY) -m arena.cli demo

gate:            ## Committed report must match a fresh eval (wall clock excluded)
	$(PY) -m arena.cli gate

interview:       ## Print the interview walkthrough
	./scripts/interview_talk.sh

lint:            ## Ruff lint and format check
	$(PY) -m ruff check arena tests
	$(PY) -m ruff format --check arena tests

capture:         ## Screenshots, gif, and mp4 from the running UI
	node scripts/capture_ui.mjs

clean:           ## Drop caches
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
