"""Admin console: model configuration versions, providers and system status."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi import status as http_status

from app.api.deps import AdminDep, RuntimeDep, SessionDep
from app.api.schemas import ConfigVersionCreate
from app.core.exceptions import NotFoundError
from app.services import config_admin
from app.utils import ffmpeg as ffmpeg_utils

router = APIRouter(tags=["admin"])


@router.get("/meta")
def meta(runtime: RuntimeDep) -> dict[str, Any]:
    """Public bootstrap information for the console."""
    return {
        "app": runtime.settings.app_name,
        "env": runtime.settings.env,
        "storage_backend": runtime.settings.storage_backend,
        "config_versions": runtime.config_store.config_versions(),
        "default_workflow": runtime.config_store.default_workflow_id(),
        "workflows": [
            {"id": item.id, "name": item.name, "version": item.version}
            for item in runtime.config_store.workflows().values()
        ],
        "agents": runtime.config_store.agent_ids(),
    }


@router.get("/admin/model-configs")
def list_model_configs(db: SessionDep, runtime: RuntimeDep, user: AdminDep) -> dict[str, Any]:
    items = config_admin.list_agent_configs(db, runtime)
    return {"items": items, "count": len(items)}


@router.get("/admin/model-configs/{agent_id}")
def get_model_config(
    agent_id: str, db: SessionDep, runtime: RuntimeDep, user: AdminDep
) -> dict[str, Any]:
    _ensure_agent(runtime, agent_id)
    versions = config_admin.list_versions(db, scope="agent", key=agent_id)
    return {
        "id": agent_id,
        "payload": config_admin.agent_config_payload(runtime, agent_id),
        "versions": [config_admin.version_public(row) for row in versions],
    }


@router.post(
    "/admin/model-configs/{agent_id}/versions", status_code=http_status.HTTP_201_CREATED
)
def create_model_config_version(
    agent_id: str,
    payload: ConfigVersionCreate,
    db: SessionDep,
    runtime: RuntimeDep,
    user: AdminDep,
) -> dict[str, Any]:
    """Persist a new immutable config version and activate it immediately."""
    _ensure_agent(runtime, agent_id)
    row = config_admin.update_agent_config(
        db,
        runtime,
        agent_id=agent_id,
        payload=payload.payload,
        user_id=user.id,
        note=payload.note,
    )
    db.flush()
    return {
        "id": agent_id,
        "version": config_admin.version_public(row),
        "applied": config_admin.agent_config_payload(runtime, agent_id),
    }


@router.get("/admin/model-configs/{agent_id}/versions")
def list_model_config_versions(
    agent_id: str, db: SessionDep, runtime: RuntimeDep, user: AdminDep
) -> dict[str, Any]:
    _ensure_agent(runtime, agent_id)
    rows = config_admin.list_versions(db, scope="agent", key=agent_id)
    return {
        "id": agent_id,
        "items": [config_admin.version_public(row) for row in rows],
        "count": len(rows),
    }


@router.post("/admin/model-configs/{agent_id}/rollback")
def rollback_model_config(
    agent_id: str, db: SessionDep, runtime: RuntimeDep, user: AdminDep
) -> dict[str, Any]:
    _ensure_agent(runtime, agent_id)
    row = config_admin.rollback(db, runtime, scope="agent", key=agent_id, user_id=user.id)
    db.flush()
    return {
        "id": agent_id,
        "version": config_admin.version_public(row),
        "applied": config_admin.agent_config_payload(runtime, agent_id),
    }


@router.delete("/admin/model-configs/{agent_id}/override")
def reset_model_config(
    agent_id: str, db: SessionDep, runtime: RuntimeDep, user: AdminDep
) -> dict[str, Any]:
    """Drop the database override so the YAML file becomes the source again."""
    _ensure_agent(runtime, agent_id)
    config_admin.reset_to_yaml(db, runtime, scope="agent", key=agent_id)
    db.flush()
    return {"id": agent_id, "applied": config_admin.agent_config_payload(runtime, agent_id)}


@router.get("/admin/model-config-versions")
def list_all_versions(
    db: SessionDep,
    user: AdminDep,
    scope: str | None = Query(default=None),
    key: str | None = Query(default=None),
) -> dict[str, Any]:
    rows = config_admin.list_versions(db, scope=scope, key=key)
    return {"items": [config_admin.version_public(row) for row in rows], "count": len(rows)}


@router.post("/admin/model-config-versions/{version_id}/activate")
def activate_version(
    version_id: str, db: SessionDep, runtime: RuntimeDep, user: AdminDep
) -> dict[str, Any]:
    row = config_admin.activate_version(db, runtime, version_id=version_id, user_id=user.id)
    db.flush()
    return {"version": config_admin.version_public(row), "applied": config_admin.agent_config_payload(runtime, row.key)}


@router.get("/admin/providers")
def list_providers(runtime: RuntimeDep, user: AdminDep) -> dict[str, Any]:
    items = config_admin.list_providers(runtime)
    return {"items": items, "count": len(items)}


@router.get("/admin/workflows")
def list_workflows(runtime: RuntimeDep, user: AdminDep) -> dict[str, Any]:
    items = config_admin.list_workflows(runtime)
    return {"items": items, "count": len(items)}


@router.get("/admin/status")
def system_status(db: SessionDep, runtime: RuntimeDep, user: AdminDep) -> dict[str, Any]:
    agents = config_admin.list_agent_configs(db, runtime)
    return {
        "app": runtime.settings.app_name,
        "env": runtime.settings.env,
        "database": runtime.settings.database_url.split("://", 1)[0],
        "storage_backend": runtime.settings.storage_backend,
        "storage_root": str(runtime.settings.storage_root),
        "ffmpeg": {
            "bin": runtime.settings.ffmpeg_bin,
            "available": ffmpeg_utils.binary_available(runtime.settings.ffmpeg_bin),
        },
        "tasks": {
            "inline": runtime.settings.inline_tasks,
            "max_workers": runtime.settings.max_workers,
        },
        "agents": {
            "count": len(agents),
            "enabled": sum(1 for item in agents if item["enabled"]),
        },
        "config_versions": runtime.config_store.config_versions(),
    }


def _ensure_agent(runtime, agent_id: str) -> None:
    if agent_id not in set(runtime.config_store.agent_ids()):
        raise NotFoundError("智能体配置不存在", details={"agent_id": agent_id})
