# 从仓库根目录构建完整 workspace，所有运行依赖使用同一 uv.lock。
# docker build -f deployment/docker/Dockerfile -t ai-film-studio .
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_PYTHON_DOWNLOADS=never

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install uv==0.12.9

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY apps ./apps
COPY packages ./packages
COPY config ./config
COPY web ./web
COPY samples ./samples
COPY scripts ./scripts

ARG INSTALL_EXTRAS=""
RUN set -eu; \
    python scripts/sync_studio_resources.py; \
    set -- uv sync --frozen --no-dev --no-editable; \
    for extra in $(printf '%s' "$INSTALL_EXTRAS" | tr ',' ' '); do \
        set -- "$@" --extra "$extra"; \
    done; \
    "$@"

ENV PATH="/app/.venv/bin:$PATH" \
    STUDIO_RESOURCE_ROOT=/app \
    APP_CONFIG_DIR=/app/config \
    APP_ENV=development \
    APP_DATA_DIR=/data \
    DATABASE_URL=sqlite:////data/studio.db \
    STORAGE_ROOT=/data/storage \
    FFMPEG_BIN=/usr/bin/ffmpeg \
    FFPROBE_BIN=/usr/bin/ffprobe

RUN mkdir -p /data/uploads /data/media /data/storage
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# 项目仍使用进程内任务；一个应用只启动一个 worker。
CMD ["uvicorn", "studio_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
