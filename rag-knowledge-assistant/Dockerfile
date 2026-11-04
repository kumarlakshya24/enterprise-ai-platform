FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
# Optional build secret `pip_ca` lets builds behind a TLS-intercepting proxy trust its CA
# without baking the certificate (or any credential) into an image layer.
RUN --mount=type=secret,id=pip_ca,required=false \
    if [ -f /run/secrets/pip_ca ]; then export PIP_CERT=/run/secrets/pip_ca; fi; \
    pip install -r requirements-dev.txt

COPY app ./app
COPY config ./config
COPY scripts ./scripts
COPY tests ./tests
COPY web ./web
COPY eval ./eval
COPY pytest.ini ./

RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/eval_results && chown appuser /app/eval_results
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
