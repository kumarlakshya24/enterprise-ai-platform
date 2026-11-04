# One image, several entrypoints: gateway, mock IdP, mock external LLM, mock local LLM.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
# spaCy model pinned by version and SHA-256.
RUN pip install -r requirements.txt \
 && pip install "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl#sha256=1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85"

COPY aegis ./aegis
COPY eval/cases ./eval/cases
COPY eval/regression ./eval/regression

# Non-root, no home directory, no login shell.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin aegis
USER 10001

EXPOSE 8080
CMD ["uvicorn", "--factory", "aegis.gateway.app:app_factory", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]
