"""Admin configuration services.

Model/provider settings live in YAML as the source of truth, but changing a model
in production must not require a redeploy or lose history.  This service keeps an
append-only ``config_versions`` ledger in the database; the newest *active* row
per ``(scope, key)`` is merged over the YAML by ``ConfigStore.apply_overrides``.

Secrets are never written here: provider rows only reference environment
variables, and API payloads expose the env var *name*, never its value.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config_models import AgentConfig
from app.core.config_store import stable_checksum
from app.core.exceptions import ConfigurationError, NotFoundError, ValidationAppError
from app.core.ids import new_id
from app.models.project import ConfigVersion
from app.services.runtime import AppRuntime

logger = logging.getLogger(__name__)

SCOPES = {"agent", "provider", "workflow"}


# --------------------------------------------------------------- load/apply
def active_overrides(db: Session) -> dict[str, dict[str, Any]]:
    rows = db.scalars(
        select(ConfigVersion).where(
            ConfigVersion.scope == "agent", ConfigVersion.is_active.is_(True)
        )
    )
    return {row.key: row.payload for row in rows}


def apply_active_config(db: Session, runtime: AppRuntime) -> None:
    runtime.config_store.apply_overrides(active_overrides(db))


# ------------------------------------------------------------------- agents
def agent_config_payload(runtime: AppRuntime, agent_id: str) -> dict[str, Any]:
    config = runtime.config_store.agent(agent_id)
    return _payload_from_config(config)


def _payload_from_config(config: AgentConfig) -> dict[str, Any]:
    return {
        "agent": config.agent.model_dump(mode="json"),
        "model": config.model.model_dump(mode="json"),
        "generation": config.generation.model_dump(mode="json"),
        "structured_output": config.structured_output.model_dump(mode="json"),
        "prompt": config.prompt.model_dump(mode="json"),
        "runtime": config.runtime.model_dump(mode="json"),
        "evaluation": config.evaluation.model_dump(mode="json"),
    }


def list_agent_configs(db: Session, runtime: AppRuntime) -> list[dict[str, Any]]:
    active = {
        row.key: row
        for row in db.scalars(
            select(ConfigVersion).where(
                ConfigVersion.scope == "agent", ConfigVersion.is_active.is_(True)
            )
        )
    }
    described: list[dict[str, Any]] = []
    for agent_id in runtime.config_store.agent_ids():
        config = runtime.config_store.agent(agent_id)
        described.append(
            {
                "id": agent_id,
                "name": config.agent.name,
                "enabled": config.agent.enabled,
                "version": config.agent.version,
                "description": config.agent.description,
                "capability": config.model.capability,
                "provider": config.model.provider,
                "model_id": config.model.model_id,
                "fallback_provider": config.model.fallback_provider,
                "fallback_model_id": config.model.fallback_model_id,
                "config_version": config.config_version,
                "source_path": config.source_path,
                "prompt_version": config.prompt.version,
                "human_review_required": config.runtime.human_review_required,
                "active_version": active[agent_id].version if agent_id in active else 0,
                "payload": _payload_from_config(config),
            }
        )
    return described


def update_agent_config(
    db: Session,
    runtime: AppRuntime,
    *,
    agent_id: str,
    payload: dict[str, Any],
    user_id: str = "",
    note: str = "",
) -> ConfigVersion:
    """Validate a full agent config, persist it as a new active version."""
    merged = dict(payload or {})
    merged.setdefault("agent", {})
    if not isinstance(merged["agent"], dict):
        raise ValidationAppError("agent 字段必须是对象")
    merged["agent"]["id"] = agent_id
    try:
        config = AgentConfig.model_validate(merged)
    except Exception as exc:
        raise ValidationAppError(f"配置校验失败: {exc}") from exc
    if config.id != agent_id:
        raise ValidationAppError("agent.id 与路径不一致")

    data = _payload_from_config(config)
    version = _next_version(db, "agent", agent_id)
    _deactivate(db, "agent", agent_id)
    row = ConfigVersion(
        id=new_id("cfgver"),
        scope="agent",
        key=agent_id,
        version=version,
        checksum=stable_checksum(data),
        payload=data,
        is_active=True,
        created_by=user_id,
        note=note or f"update agent {agent_id}",
    )
    db.add(row)
    db.flush()
    apply_active_config(db, runtime)
    logger.info("agent %s config -> v%s (%s)", agent_id, version, row.checksum)
    return row


# ----------------------------------------------------------------- versions
def _next_version(db: Session, scope: str, key: str) -> int:
    current = db.scalar(
        select(func.max(ConfigVersion.version)).where(
            ConfigVersion.scope == scope, ConfigVersion.key == key
        )
    )
    return int(current or 0) + 1


def _deactivate(db: Session, scope: str, key: str) -> None:
    db.query(ConfigVersion).filter(
        ConfigVersion.scope == scope, ConfigVersion.key == key, ConfigVersion.is_active.is_(True)
    ).update({"is_active": False}, synchronize_session=False)


def list_versions(
    db: Session, *, scope: str | None = None, key: str | None = None
) -> list[ConfigVersion]:
    statement = select(ConfigVersion)
    if scope:
        statement = statement.where(ConfigVersion.scope == scope)
    if key:
        statement = statement.where(ConfigVersion.key == key)
    return list(db.scalars(statement.order_by(ConfigVersion.created_at.desc())))


def get_version(db: Session, version_id: str) -> ConfigVersion:
    row = db.get(ConfigVersion, version_id)
    if row is None:
        raise NotFoundError("配置版本不存在", details={"version_id": version_id})
    return row


def activate_version(
    db: Session, runtime: AppRuntime, *, version_id: str, user_id: str = ""
) -> ConfigVersion:
    row = get_version(db, version_id)
    if row.scope != "agent":
        raise ValidationAppError(f"暂不支持激活 scope='{row.scope}' 的配置版本")
    _deactivate(db, row.scope, row.key)
    row.is_active = True
    db.flush()
    apply_active_config(db, runtime)
    logger.info("config version %s (%s/%s v%s) activated by %s", row.id, row.scope, row.key, row.version, user_id)
    return row


def rollback(
    db: Session, runtime: AppRuntime, *, scope: str, key: str, user_id: str = ""
) -> ConfigVersion:
    """Activate the newest inactive version (i.e. undo the last change)."""
    rows = list(
        db.scalars(
            select(ConfigVersion)
            .where(ConfigVersion.scope == scope, ConfigVersion.key == key)
            .order_by(ConfigVersion.version.desc())
        )
    )
    if not rows:
        raise NotFoundError("没有可回滚的配置版本", details={"scope": scope, "key": key})
    target = next((row for row in rows if not row.is_active), None)
    if target is None:
        raise ValidationAppError("没有更早的配置版本可回滚")
    _deactivate(db, scope, key)
    target.is_active = True
    db.flush()
    apply_active_config(db, runtime)
    return target


def reset_to_yaml(
    db: Session, runtime: AppRuntime, *, scope: str, key: str
) -> None:
    _deactivate(db, scope, key)
    db.flush()
    apply_active_config(db, runtime)


# ---------------------------------------------------------------- read-only
def list_providers(runtime: AppRuntime) -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []
    for capability in ("llm", "vision", "image", "video", "audio"):
        for name, config in sorted(runtime.config_store.providers(capability).items()):
            providers.append(
                {
                    "name": name,
                    "capability": config.capability,
                    "enabled": config.enabled,
                    "kind": config.kind,
                    "models": list(config.models),
                    "api_key_env": config.api_key_env,
                    "base_url_env": config.base_url_env,
                    "has_api_key": bool(config.api_key()),
                    "timeout_seconds": config.timeout_seconds,
                    "max_concurrency": config.max_concurrency,
                    "protocol": config.extra.get("protocol"),
                }
            )
    return providers


def list_workflows(runtime: AppRuntime) -> list[dict[str, Any]]:
    workflows: list[dict[str, Any]] = []
    for workflow_id, config in sorted(runtime.config_store.workflows().items()):
        workflows.append(
            {
                "id": workflow_id,
                "name": config.name,
                "version": config.version,
                "description": config.description,
                "config_version": config.config_version,
                "source_path": config.source_path,
                "nodes": [
                    {
                        "id": node.id,
                        "type": node.type,
                        "handler": node.handler,
                        "agent": node.agent,
                        "review_stage": node.review_stage,
                        "title": node.title,
                        "continue_on_error": node.continue_on_error,
                    }
                    for node in config.nodes
                ],
            }
        )
    return workflows


def version_public(row: ConfigVersion) -> dict[str, Any]:
    return {
        "id": row.id,
        "scope": row.scope,
        "key": row.key,
        "version": row.version,
        "checksum": row.checksum,
        "is_active": row.is_active,
        "created_by": row.created_by,
        "note": row.note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "payload": row.payload,
    }


def ensure_consistent(db: Session, runtime: AppRuntime) -> None:
    """Fail fast at boot when a DB override no longer matches the schema."""
    try:
        apply_active_config(db, runtime)
    except ConfigurationError:
        logger.exception("stored configuration overrides are invalid")
        raise
