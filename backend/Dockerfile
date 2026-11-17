# syntax=docker/dockerfile:1.7
# Multi-stage build (Ch. 15.3): `development` for compose override, `production` for clusters.

FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# libgomp: OpenMP runtime needed by LightGBM / XGBoost
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# ---- dependencies are installed into a virtualenv that later stages copy ----
FROM base AS deps
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements/ requirements/
RUN pip install -r requirements/prod.txt

FROM deps AS dev-deps
RUN pip install -r requirements/dev.txt

# ---- development: hot reload, source mounted by docker-compose.override.yml ----
FROM base AS development
COPY --from=dev-deps /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---- production: non-root, gunicorn managing uvicorn workers ----
FROM base AS production
RUN useradd --create-home --uid 10001 aquaintel
COPY --from=deps /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH AQUAINTEL_ENVIRONMENT=production
COPY --chown=aquaintel:aquaintel alembic.ini pyproject.toml ./
COPY --chown=aquaintel:aquaintel app/ app/
COPY --chown=aquaintel:aquaintel scripts/ scripts/
RUN mkdir -p var && chown aquaintel:aquaintel var
USER aquaintel
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fsS http://localhost:8000/health/live || exit 1
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "4", "-b", "0.0.0.0:8000", \
     "--graceful-timeout", "30", "--access-logfile", "-"]
