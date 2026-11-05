"""FastAPI composition root.

Only application assembly belongs here. Resource lifecycle, system endpoints,
API feature routes and static console mounting live in their respective layers.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.api.routes.system import build_system_router
from app.bootstrap.lifespan import create_lifespan
from app.console import ConsoleStaticFiles
from app.modules.platform.exceptions import AppError
from app.modules.platform.public import Settings, load_settings
from app.modules.platform.storage import StorageError

logger = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parents[2] / "web"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="配置驱动的多智能体 AI 影视生产平台",
        lifespan=create_lifespan(settings),
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
    app.include_router(build_system_router(settings))
    _mount_console(app)
    return app


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
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
    return [
        {
            "loc": [str(part) for part in item.get("loc", [])],
            "msg": item.get("msg", ""),
            "type": item.get("type", ""),
        }
        for item in exc.errors()
    ]


def _mount_console(app: FastAPI) -> None:
    if WEB_DIR.is_dir():
        # Mounted last: API and media routes are matched first.
        app.mount("/", ConsoleStaticFiles(directory=WEB_DIR), name="console")
        return

    logger.warning("web console directory not found: %s", WEB_DIR)

    @app.get("/", include_in_schema=False)
    def index() -> dict:
        return {"message": "AI Film Studio API", "docs": "/docs"}


app = create_app()
