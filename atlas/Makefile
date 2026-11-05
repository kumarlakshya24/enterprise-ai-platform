# Atlas durable workflows. Run `make help`.
PY ?= python3

.PHONY: lint help install up test eval demo kill-resume interview clean

help:            ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

install:         ## Install runtime and test dependencies
	$(PY) -m pip install -r requirements-dev.txt

up:              ## Run the demo API and UI on :8096 (SQLite, no Docker)
	mkdir -p var
	$(PY) -m atlas serve

lint:            ## Ruff lint + format check
	$(PY) -m ruff check atlas tests scripts
	$(PY) -m ruff format --check atlas tests scripts

test:            ## Unit and integration tests, including kill-and-resume
	$(PY) -m pytest -q

eval:            ## Offline suite: Atlas vs a single-agent baseline -> eval_results/
	mkdir -p var
	$(PY) -m atlas eval

demo:            ## Print a short happy-path trace
	$(PY) -m atlas demo

kill-resume:     ## SIGKILL a worker after a ledger debit, resume, prove one debit
	$(PY) -m atlas kill-resume

interview:       ## Print the interview walkthrough
	@sh scripts/interview_talk.sh

clean:           ## Remove local databases and caches
	rm -rf var .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
