.PHONY: setup models up down test lint eval demo calibrate
export APP_UID := $(shell id -u)
export APP_GID := $(shell id -g)

setup:            ## local venv for development
	python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

models:           ## download + verify ONNX models, build int8 re-ranker
	python scripts/fetch_models.py

up:               ## start Postgres, Redis and the API
	docker compose up -d --build

down:
	docker compose down

test:             ## unit + integration tests (needs db + redis running)
	docker compose run --rm api pytest -q

lint:             ## Ruff lint + format check (same settings as the sibling projects)
	$(or $(PY),python3) -m ruff check app tests scripts
	$(or $(PY),python3) -m ruff format --check app tests scripts

eval:             ## full evaluation suite -> eval_results/latest
	docker compose run --rm api python -m app.evaluation.runner

demo:             ## baseline vs full, side by side
	docker compose run --rm api python scripts/demo.py

calibrate:        ## choose refusal thresholds on the held-out calibration set
	docker compose run --rm api python scripts/calibrate.py
