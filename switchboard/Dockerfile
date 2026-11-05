FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SWITCHBOARD_HOST=0.0.0.0 \
    SWITCHBOARD_PORT=8092 \
    SWITCHBOARD_DB=/tmp/switchboard.db

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY switchboard ./switchboard
COPY pyproject.toml README.md ./

EXPOSE 8092
USER nobody
CMD ["python", "-m", "switchboard"]
