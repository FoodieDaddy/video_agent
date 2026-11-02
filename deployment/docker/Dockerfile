# ---- AI Film Studio image ---------------------------------------------------
# Build from the repository root so the layout under /app mirrors the checkout:
#   docker build -f deployment/docker/Dockerfile -t ai-film-studio .
#
# The app resolves config/, data/ and web/ relative to the repository root
# (see app/core/settings.py::REPO_ROOT), which is why /app keeps that layout.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg/ffprobe do the real media work; curl is only for the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependency layer first for better caching.
COPY pyproject.toml ./
COPY backend ./backend
ARG INSTALL_EXTRAS=""
RUN if [ -n "$INSTALL_EXTRAS" ]; then pip install ".[${INSTALL_EXTRAS}]"; else pip install .; fi

# Runtime assets that are read from disk rather than packaged: YAML config,
# prompts, the console, the sample novel and the CLI scripts.
COPY config ./config
COPY web ./web
COPY samples ./samples
COPY scripts ./scripts

# Single-container defaults: local storage, SQLite under /data, tasks in-process.
# docker-compose.yml overrides APP_ENV; keep allow_dev_auth disabled for prod.
ENV APP_ENV=development \
    APP_DATA_DIR=/data \
    DATABASE_URL=sqlite:////data/studio.db \
    STORAGE_ROOT=/data/storage \
    FFMPEG_BIN=/usr/bin/ffmpeg \
    FFPROBE_BIN=/usr/bin/ffprobe

RUN mkdir -p /data/uploads /data/media /data/storage

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# One worker on purpose: tasks run in-process (tasks.inline) and the SSE stream
# reads task_events from SQLite. Scale out only with PostgreSQL + a real worker.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
