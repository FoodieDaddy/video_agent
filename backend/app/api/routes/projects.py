"""Project lifecycle and the aggregate dashboard endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, status

from app.api.deps import (
    RuntimeDep,
    SessionDep,
    UserDep,
    owner_project,
    project_scope,
)
from app.api.schemas import ProjectCreate, ProjectUpdate
from app.api.serializers import dashboard, project_public
from app.services import assets as asset_service
from app.services import projects as project_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
def list_projects(
    db: SessionDep,
    user: UserDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    rows = project_service.list_projects(db, user.id, limit=limit)
    return {"items": [project_public(project) for project in rows], "count": len(rows)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: SessionDep,
    user: UserDep,
) -> dict[str, Any]:
    project = project_service.create_project(
        db,
        owner_id=user.id,
        name=payload.name,
        description=payload.description,
        language=payload.language,
        genre=payload.genre,
        budget_limit_usd=payload.budget_limit_usd,
        settings={**payload.settings, "aspect_ratio": payload.aspect_ratio},
    )
    project.aspect_ratio = payload.aspect_ratio
    db.flush()
    return project_public(project)


@router.get("/{project_id}")
def get_project(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    return project_public(project_scope(db, project_id, user))


@router.patch("/{project_id}")
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: SessionDep,
    user: UserDep,
) -> dict[str, Any]:
    project = owner_project(db, project_id, user)
    data = payload.model_dump(exclude_unset=True)
    if "settings" in data and data["settings"] is not None:
        project.settings = {**(project.settings or {}), **data.pop("settings")}
    for field in ("name", "description", "aspect_ratio", "budget_limit_usd"):
        if data.get(field) is not None:
            setattr(project, field, data[field])
    db.flush()
    return project_public(project)


@router.get("/{project_id}/dashboard")
def project_dashboard(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    return dashboard(db, project)


@router.get("/{project_id}/assets")
def list_assets(
    project_id: str,
    db: SessionDep,
    user: UserDep,
    kind: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = asset_service.list_assets(db, project.id, kind=kind, limit=limit)
    return {"items": [asset_service.asset_public(asset) for asset in rows], "count": len(rows)}


@router.get("/{project_id}/summary")
def project_summary(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    from app.services import pipeline

    project = project_scope(db, project_id, user)
    return pipeline.project_summary(db, project)


@router.get("/{project_id}/meta")
def project_meta(project_id: str, runtime: RuntimeDep, db: SessionDep, user: UserDep) -> dict[str, Any]:
    """What the console needs to render selectors (workflows, agents, config)."""
    project = project_scope(db, project_id, user)
    return {
        "project_id": project.id,
        "workflows": [
            {"id": workflow.id, "name": workflow.name, "version": workflow.version}
            for workflow in runtime.config_store.workflows().values()
        ],
        "agents": runtime.config_store.agent_ids(),
        "config_versions": runtime.config_store.config_versions(),
    }
