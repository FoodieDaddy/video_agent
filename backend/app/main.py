"""FastAPI application factory.

Boot order matters: settings → engine/schema → runtime singletons → stored
config overrides.  Doing it in a lifespan handler keeps imports side-effect
free, which is what the tests rely on when they build isolated apps.
"""

from __future__ import annotations

import logging
import mimetypes
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.router import api_router
from app.core.exceptions import AppError
from app.core.settings import Settings, load_settings
from app.db.session import init_engine, init_schema, reset_engine, session_scope
from app.services import config_admin
from app.services import tasks as task_service
from app.services.runtime import build_runtime, reset_runtime, set_runtime
from app.utils.storage import LocalStorage, StorageError

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Iterator[None]:
        runtime = build_runtime(settings)
        set_runtime(runtime)
        init_engine(settings)
        init_schema()
        with session_scope() as db:
            config_admin.ensure_consistent(db, runtime)
        app.state.runtime = runtime
        logger.info(
            "%s started (env=%s, db=%s, storage=%s)",
            settings.app_name,
            settings.env,
            settings.database_url.split("://", 1)[0],
            settings.storage_backend,
        )
        try:
            yield
        finally:
            runtime = getattr(app.state, "runtime", None)
            if runtime is not None:
                task_service.reset_runner(runtime)
            reset_runtime()
            reset_engine()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="配置驱动的多智能体 AI 影视生产平台",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.get("api", "cors_origins", default=["*"]) or ["*"]),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_error_handlers(app)
    app.include_router(api_router)
    _register_system_routes(app, settings)
    _mount_console(app)
    return app


# ------------------------------------------------------------------- errors
def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "请求参数校验失败",
                    "details": {"errors": _jsonable_errors(exc)},
                }
            },
        )

    @app.exception_handler(StorageError)
    async def _storage_error(request: Request, exc: StorageError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": str(exc), "details": {}}},
        )


def _jsonable_errors(exc: RequestValidationError) -> list[dict]:
    errors: list[dict] = []
    for item in exc.errors():
        errors.append(
            {
                "loc": [str(part) for part in item.get("loc", [])],
                "msg": item.get("msg", ""),
                "type": item.get("type", ""),
            }
        )
    return errors


# ------------------------------------------------------------------ system
def _register_system_routes(app: FastAPI, settings: Settings) -> None:
    @app.get("/health", tags=["system"])
    def health() -> dict:
        database = "ok"
        with session_scope() as db:
            db.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "app": settings.app_name,
            "env": settings.env,
            "database": database,
            "storage": settings.storage_backend,
        }

    @app.get("/media/{storage_key:path}", tags=["media"])
    def media(storage_key: str):
        """Serve stored objects for local development.

        In production media is served by the object store/CDN; this route keeps
        the console usable without extra infrastructure.
        """
        runtime = app.state.runtime
        storage = runtime.storage
        if isinstance(storage, LocalStorage):
            path = storage.path_for(storage_key)
            if not path.is_file():
                raise StorageError("媒体文件不存在")
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            return FileResponse(path, media_type=mime, filename=path.name)
        content = storage.read_bytes(storage_key)
        mime = mimetypes.guess_type(storage_key)[0] or "application/octet-stream"
        return Response(content=content, media_type=mime)


def _mount_console(app: FastAPI) -> None:
    if WEB_DIR.is_dir():
        # Mounted last: API and media routes are matched first.
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="console")
    else:  # pragma: no cover - only when the console is not shipped
        logger.warning("web console directory not found: %s", WEB_DIR)

        @app.get("/", include_in_schema=False)
        def index() -> dict:
            return {"message": "AI Film Studio API", "docs": "/docs"}


app = create_app()
