# Charter. Offline AI governance control plane. Run `make help`.
PY ?= python3

.PHONY: help install up test eval gate gate-weakened demo evidence interview lint typecheck format ci clean fixtures

help:            ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

install:         ## Install runtime and dev dependencies
	$(PY) -m pip install -r requirements-dev.txt

fixtures:        ## Rewrite the synthetic Aegis audit log from the generator
	$(PY) -c "from charter.ingest.aegis import write_fixture; from charter.config import AUDIT_PATH; write_fixture(AUDIT_PATH)"

up:              ## Serve the demo UI on http://127.0.0.1:8097
	$(PY) -m charter.cli serve --port $${CHARTER_PORT:-8097}

test:            ## Unit tests. No network, no API key.
	$(PY) -m pytest -q -W ignore::DeprecationWarning

eval:            ## Decisions, matrix, evidence. Fails if the residency file can be deleted quietly.
	$(PY) -m charter.cli eval

gate:            ## Locked cases against the shipped policies. Exits 0.
	$(PY) -m charter.cli gate

gate-weakened:   ## Same cases without 002-residency.cedar. Exits 1.
	$(PY) -m charter.cli gate --weakened

demo:            ## Print the allow, the blocked residency call, and the gap
	$(PY) -m charter.cli demo

evidence:        ## Print the evidence pack
	$(PY) -m charter.cli evidence

interview:       ## Print the interview walkthrough
	bash scripts/interview_talk.sh

lint:            ## Ruff
	$(PY) -m ruff check charter tests
	$(PY) -m ruff format --check charter tests

typecheck:       ## mypy
	$(PY) -m mypy

format:          ## Auto-format
	$(PY) -m ruff format charter tests
	$(PY) -m ruff check --fix charter tests

ci: test eval    ## What the workflow's main job runs, plus its explicit gate steps

clean:           ## Drop caches
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache
