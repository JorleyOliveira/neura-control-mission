FROM python:3.13-slim AS dependencies

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./

RUN pip install --prefix=/install -r requirements.txt


FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 app \
    && useradd \
        --uid 1000 \
        --gid app \
        --home-dir /app \
        --shell /usr/sbin/nologin \
        app \
    && mkdir -p \
        /app/state \
        /workspace \
        /app/data/skills \
    && chown -R app:app \
        /app \
        /workspace

COPY --from=dependencies /install /usr/local

COPY --chown=app:app neura_marketplace/ ./neura_marketplace/
COPY --chown=app:app scripts/ ./scripts/
COPY --chown=app:app tests/ ./tests/
COPY --chown=app:app data/ ./data/

COPY --chown=app:app \
    pyproject.toml \
    requirements.txt \
    ./

USER app

CMD ["python", "-m", "uvicorn", "neura_marketplace.jarvis_app:app", "--host", "0.0.0.0", "--port", "8000"]