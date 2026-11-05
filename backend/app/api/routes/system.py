"""System and local-media endpoints kept outside the application composition root."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import text

from app.modules.platform.persistence.session import session_scope
from app.modules.platform.public import Settings
from app.modules.platform.storage import LocalStorage, StorageError


def build_system_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["system"])

    @router.get("/health")
    def health() -> dict:
        with session_scope() as db:
            db.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "app": settings.app_name,
            "env": settings.env,
            "database": "ok",
            "storage": settings.storage_backend,
        }

    @router.get("/media/{storage_key:path}", tags=["media"])
    def media(storage_key: str, request: Request):
        """Serve media through the configured storage adapter in local deployments."""
        runtime = request.app.state.runtime
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

    return router
