"""Shared FastAPI dependencies.

Identity comes from the header based dev auth in :mod:`app.core.security`;
project isolation is enforced here once so no router has to remember it.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.security import CurrentUser, get_admin_user, get_current_user
from app.db.session import get_db
from app.models.project import Project
from app.services import projects as project_service
from app.services import tasks as task_service
from app.services.runtime import AppRuntime, get_runtime

SessionDep = Annotated[Session, Depends(get_db)]
UserDep = Annotated[CurrentUser, Depends(get_current_user)]
AdminDep = Annotated[CurrentUser, Depends(get_admin_user)]


def runtime_dep() -> AppRuntime:
    return get_runtime()


RuntimeDep = Annotated[AppRuntime, Depends(runtime_dep)]


def project_scope(db: Session, project_id: str, user: CurrentUser, *, role: str | None = None) -> Project:
    """Load a project and verify the caller may touch it."""
    return project_service.get_project(db, project_id, user.id, require_role=role)


def owner_project(db: Session, project_id: str, user: CurrentUser) -> Project:
    return project_scope(db, project_id, user, role="editor")


def resolve_project_of(db: Session, entity_project_id: str, user: CurrentUser) -> Project:
    """Used by ``/{resource}/{id}`` routes that are not project-scoped."""
    return project_scope(db, entity_project_id, user)


async def run_task(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    type: str,
    payload: dict[str, Any] | None = None,
    user_id: str = "",
    wait: bool = False,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Enqueue a background task and optionally wait for its first result.

    ``wait`` exists for the console and the tests: the API stays asynchronous
    by default, but a caller may ask for the finished task in one round trip.
    """
    task = task_service.enqueue(
        db, runtime, project=project, type=type, payload=payload or {}, user_id=user_id
    )
    if wait:
        await asyncio.to_thread(task_service.get_runner(runtime).wait, task.id, timeout)
        db.expire_all()
        task = task_service.get_task(db, project.id, task.id)
    return {
        "task_id": task.id,
        "status": task.status,
        "task": task_service.task_public(task),
    }


def not_found(message: str, **details: Any) -> NotFoundError:
    return NotFoundError(message, details=details)
