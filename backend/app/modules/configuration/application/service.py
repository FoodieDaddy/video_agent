"""配置管理用例：以 YAML 为基础，将已激活的 Agent 配置叠加到运行时。

配置内容以新增版本记录保留，激活标记可更新；当前只将 agent scope 应用为
运行时覆盖，不应描述为所有 Provider/Workflow 都已支持在线版本切换。
用例只 flush，由调用方提交事务；内存覆盖不会随着数据库回滚自动撤销。
供应商查询返回密钥来源和是否存在，不返回解析后的密钥值。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.configuration.infrastructure.persistence.models import ConfigVersion
from app.modules.platform.configuration.config_models import AgentConfig
from app.modules.platform.configuration.config_store import stable_checksum
from app.modules.platform.exceptions import ConfigurationError, NotFoundError, ValidationAppError
from app.modules.platform.execution.runtime import AppRuntime
from app.modules.platform.ids import new_id

logger = logging.getLogger(__name__)

SCOPES = {"agent", "provider", "workflow"}


# --------------------------------------------------------------- load/apply
def active_overrides(db: Session) -> dict[str, dict[str, Any]]:
    """读取激活的 Agent 覆盖；写入用例负责维持每个 key 的激活唯一性。"""
    rows = db.scalars(
        select(ConfigVersion).where(ConfigVersion.scope == "agent", ConfigVersion.is_active.is_(True))
    )
    return {row.key: row.payload for row in rows}


def apply_active_config(db: Session, runtime: AppRuntime) -> None:
    """将当前会话可见的覆盖应用到内存；不提交数据库或冻结进行中的运行。"""
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
            select(ConfigVersion).where(ConfigVersion.scope == "agent", ConfigVersion.is_active.is_(True))
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
    """校验完整 Agent 配置，新增激活版本并立即更新内存覆盖。

    Args:
        db: 调用方事务；权限检查由 API 等上层入口完成。
        agent_id: 路径指定的 Agent 标识，将覆盖 payload 中的 agent.id。
        payload: 按 AgentConfig 校验的完整配置，不是局部 patch。

    Returns:
        新增且已 flush 的 ConfigVersion，仍绑定当前会话。

    Raises:
        ValidationAppError: agent 字段不是对象，或配置未通过模型校验。
        ConfigurationError: 运行时应用覆盖时发现不兼容配置。

    Notes:
        不提交事务。相同 payload 重复调用也分配新版本；max+1 不构成
        并发版本分配保证。内存先于外层提交更新，外层回滚不会自动恢复内存。
    """
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
        select(func.max(ConfigVersion.version)).where(ConfigVersion.scope == scope, ConfigVersion.key == key)
    )
    return int(current or 0) + 1


def _deactivate(db: Session, scope: str, key: str) -> None:
    db.query(ConfigVersion).filter(
        ConfigVersion.scope == scope, ConfigVersion.key == key, ConfigVersion.is_active.is_(True)
    ).update({"is_active": False}, synchronize_session=False)


def list_versions(db: Session, *, scope: str | None = None, key: str | None = None) -> list[ConfigVersion]:
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
    """重新激活指定 Agent 版本；版本不存在或 scope 不支持时抛出业务异常。

    停用同 scope/key 的其他记录后 flush 并更新内存，不提交事务。
    返回会话中的版本对象；外层回滚不会自动撤销内存覆盖。
    """
    row = get_version(db, version_id)
    if row.scope != "agent":
        raise ValidationAppError(f"暂不支持激活 scope='{row.scope}' 的配置版本")
    _deactivate(db, row.scope, row.key)
    row.is_active = True
    db.flush()
    apply_active_config(db, runtime)
    logger.info(
        "config version %s (%s/%s v%s) activated by %s", row.id, row.scope, row.key, row.version, user_id
    )
    return row


def rollback(db: Session, runtime: AppRuntime, *, scope: str, key: str, user_id: str = "") -> ConfigVersion:
    """激活版本号最大的非激活记录，并立即重新应用 Agent 覆盖。

    Raises:
        NotFoundError: scope/key 没有任何版本记录。
        ValidationAppError: 没有可选的非激活版本。

    Notes:
        只 flush、不提交；不是撤销日志栈，多次调用可能在版本间切换。
        运行时仅应用 agent scope；数据库回滚不自动撤销内存变更。
    """
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


def reset_to_yaml(db: Session, runtime: AppRuntime, *, scope: str, key: str) -> None:
    """停用指定 scope/key 的数据库覆盖并重载内存；只 flush，不删除历史。"""
    _deactivate(db, scope, key)
    db.flush()
    apply_active_config(db, runtime)


# ---------------------------------------------------------------- read-only
def list_providers(runtime: AppRuntime) -> list[dict[str, Any]]:
    """列出供应商配置及密钥来源，不发健康请求，也不返回密钥原值。

    环境引用解析错误会传播；has_api_key 只表示能读到值，不证明鉴权成功。
    """
    providers: list[dict[str, Any]] = []
    for capability in ("llm", "vision", "image", "video", "audio"):
        for name, config in sorted(runtime.config_store.providers(capability).items()):
            providers.append(
                {
                    "name": name,
                    "capability": config.capability,
                    "enabled": config.enabled,
                    "protocol": config.protocol_name(),
                    "url": config.resolved_url(),
                    "models": list(config.models),
                    "api_key": config.api_key_source(),
                    "has_api_key": bool(config.resolved_api_key()),
                    "timeout_seconds": config.timeout_seconds,
                    "max_concurrency": config.max_concurrency,
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
    """启动时应用数据库覆盖；ConfigurationError 保留日志后继续抛出。"""
    try:
        apply_active_config(db, runtime)
    except ConfigurationError:
        logger.exception("stored configuration overrides are invalid")
        raise
