# hospital-queue-ai API. Build context: backend/ (docker compose service `backend`).
# The image only reads Postgres tables: no ML code, models, data or training dependencies.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend

# Dependencies first (cached until pyproject.toml changes). A stub package lets pip resolve the project.
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py \
    && pip install . \
    && pip uninstall -y hqai-backend \
    && rm -rf app build *.egg-info

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app \
    && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# Schema first (idempotent), then the API.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
