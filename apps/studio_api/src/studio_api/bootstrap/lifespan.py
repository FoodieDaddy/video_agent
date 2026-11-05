"""Application resource lifecycle.

The composition root owns startup/shutdown ordering; route modules and business
modules must not initialize process-global resources during import.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from studio_api.bootstrap.composition import configure_application
from studio_configuration import public as config_admin
from studio_platform.execution import task_runner as task_service
from studio_platform.persistence.session import init_engine, init_schema, reset_engine, session_scope
from studio_platform.public import Settings, build_runtime, reset_runtime, set_runtime

logger = logging.getLogger(__name__)


def create_lifespan(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Build a FastAPI lifespan with deterministic resource ownership."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_application()
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
            active_runtime = getattr(app.state, "runtime", None)
            if active_runtime is not None:
                task_service.reset_runner(active_runtime)
            reset_runtime()
            reset_engine()

    return lifespan
