# Forge local targets. Run `make help`.

PY ?= python3
export PY

.PHONY: help install test demo eval regression interview bench security-check up serve lint ci clean

help: ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

install: ## Install runtime and test dependencies
	$(PY) -m pip install -r requirements-dev.txt

test: ## Unit and integration tests
	$(PY) -m pytest -q -W ignore::DeprecationWarning

demo: ## PASS/FAIL scenarios, including the regression gate
	$(PY) scripts/demo.py

eval: ## Corpus, regression gate, and latency into reports/
	$(PY) eval/run_eval.py
	$(PY) bench/latency.py

regression: ## Re-run the regression gate
	$(PY) eval/run_regression.py

interview: ## Live interview beats (writes reports/interview.md)
	$(PY) scripts/interview.py

bench: ## Sandbox and deny-path latency
	$(PY) bench/latency.py

security-check: ## Look for secrets and shell execution in the package
	$(PY) scripts/security_check.py

up: ## Serve the local UI on 127.0.0.1:8095
	$(PY) -m uvicorn forge.api.app:app --host 127.0.0.1 --port $${FORGE_PORT:-8095}

serve: up ## Alias for up

lint: ## Ruff lint and format check
	$(PY) -m ruff check forge tests eval bench scripts
	$(PY) -m ruff format --check forge tests eval bench scripts

ci: lint test eval security-check ## What CI should run

clean: ## Remove local workspace state and caches
	rm -rf var .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
