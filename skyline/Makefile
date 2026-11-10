# Skyline. Offline platform synth for Aegis, Lumen, and Switchboard. Run `make help`.
PY ?= python3

.PHONY: help install up test eval synth diff gate gate-seeded demo interview lint typecheck format ci clean

help:            ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

install:         ## Install runtime and dev dependencies
	$(PY) -m pip install -r requirements-dev.txt

up:              ## Serve the FinOps console on http://127.0.0.1:8097
	$(PY) -m skyline serve --port $${SKYLINE_PORT:-8097}

test:            ## Unit tests. No network, no AWS account.
	$(PY) -m pytest -q -W ignore::DeprecationWarning

eval:            ## Synth, diff, invariants, guardrail, FinOps. Rewrites the README results.
	$(PY) -m skyline eval

synth:           ## Write build/assembly.json and diff it against the fixture
	$(PY) -m skyline synth

diff:            ## Exit 1 when the synth drifts from fixtures/assembly.json
	$(PY) -m skyline diff

gate:            ## Architecture invariants on the clean synth. Exits 0.
	$(PY) -m skyline gate

gate-seeded:     ## Open the security group to the world. Exits 1.
	$(PY) -m skyline gate --mutation open-sg

demo:            ## Print the 60-second walkthrough
	$(PY) -m skyline demo

interview:       ## Print the interview walkthrough
	bash scripts/interview_talk.sh

lint:            ## Ruff
	$(PY) -m ruff check skyline tests
	$(PY) -m ruff format --check skyline tests

typecheck:       ## mypy
	$(PY) -m mypy

format:          ## Auto-format
	$(PY) -m ruff format skyline tests
	$(PY) -m ruff check --fix skyline tests

ci: test eval    ## What CI runs, plus the workflow's explicit gate steps

clean:           ## Drop caches and the local synth output
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache build
