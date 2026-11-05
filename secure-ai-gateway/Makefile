# Aegis secure AI gateway. Run `make help`.
PY ?= python3
SPACY_MODEL = en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl\#sha256=1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85

.PHONY: help install env up run down logs run-local demo test lint typecheck format redteam regression \
        regression-update benchmark benchmark-live train security-check ci clean

help:            ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

install:         ## Install dev dependencies and the spaCy model into the current Python
	$(PY) -m pip install -r requirements-dev.txt
	$(PY) -m pip install "$(SPACY_MODEL)"

env:             ## Create .env with fresh random keys (never overwrites)
	$(PY) scripts/init_env.py

up: env          ## Build and start the full stack (gateway, Postgres, Redis, IdP, mock LLMs)
	docker compose up --build -d --wait
	@echo "UI: http://localhost:8080   third-party log: http://localhost:8090/_evidence/received"

run: up          ## Alias for `up`

down:            ## Stop the stack (keeps the Postgres volume; `docker compose down -v` to wipe)
	docker compose down

logs:            ## Follow gateway logs
	docker compose logs -f gateway

run-local:       ## Run everything without Docker (SQLite, in-memory vault)
	$(PY) scripts/run_local.py

demo:            ## Run all five scenarios against a running gateway and check the outcomes
	$(PY) scripts/demo.py --base-url $${AEGIS_URL:-http://localhost:8080}

test:            ## Unit + integration tests
	$(PY) -m pytest -q -W ignore::DeprecationWarning

lint:            ## Ruff lint + format check
	$(PY) -m ruff check aegis tests eval bench scripts
	$(PY) -m ruff format --check aegis tests eval bench scripts

typecheck:       ## mypy (strict-ish) over the aegis package
	$(PY) -m mypy

format:          ## Auto-format
	$(PY) -m ruff format aegis tests eval bench scripts
	$(PY) -m ruff check --fix aegis tests eval bench scripts

redteam:         ## Red-team suite: precision, recall, FP, FN -> reports/redteam.md
	$(PY) eval/run_redteam.py

regression:      ## DLP regression gate: fails if a protected case regresses -> reports/regression.md
	$(PY) eval/run_regression.py

regression-update: ## Grow the regression baseline (refuses if anything regressed)
	$(PY) eval/run_regression.py --update

benchmark:       ## In-process latency benchmark -> reports/latency.md
	$(PY) bench/latency.py

benchmark-live:  ## Latency against the running compose stack (Postgres + Redis in the loop)
	$(PY) bench/latency.py --url $${AEGIS_URL:-http://localhost:8080} --label compose --n 100

train:           ## Regenerate synthetic training data and retrain the classifier -> reports/classifier.md
	$(PY) scripts/generate_classifier_data.py
	$(PY) -m aegis.classifier.train

security-check:  ## Automated security checklist (secrets, synthetic data, hardening)
	$(PY) scripts/security_check.py

ci: lint typecheck test regression redteam security-check  ## Everything CI runs

clean:           ## Remove local databases and caches
	rm -f aegis.db aegis-local.db
	find . -name __pycache__ -type d -prune -exec rm -r {} +
