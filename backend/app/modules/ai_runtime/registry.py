"""可执行 Agent 注册表。

运行机制只认识通用 BaseAgent，不静态导入业务 Agent。应用组合根负责提供
默认实现；旧调用方首次查询或执行时也可惰性触发同一次装配。
"""

from __future__ import annotations

from threading import RLock

from app.modules.ai_runtime.base import BaseAgent
from app.modules.platform.configuration.config_store import ConfigStore
from app.modules.platform.exceptions import ConfigurationError

AGENT_CLASSES: dict[str, type[BaseAgent]] = {}
_registration_lock = RLock()
_builtins_registered = False


def register_agent_classes(classes: dict[str, type[BaseAgent]]) -> None:
    """由组合根装配默认实现；重复注册同一类可重入，冲突不会静默覆盖。"""
    global _builtins_registered
    with _registration_lock:
        for agent_id, implementation in classes.items():
            previous = AGENT_CLASSES.get(agent_id)
            if previous is not None and previous is not implementation:
                raise ConfigurationError(f"Agent type '{agent_id}' is already registered")
        AGENT_CLASSES.update(classes)
        _builtins_registered = True


def _ensure_registered() -> None:
    if _builtins_registered:
        return
    with _registration_lock:
        if not _builtins_registered:
            # 组合根是惰性装配边界；业务实现只由该位置导入一次。
            from app.bootstrap.agent_catalog import register_agents

            register_agents()


def agent_ids() -> list[str]:
    _ensure_registered()
    return sorted(AGENT_CLASSES)


def create_agent(agent_id: str, config_store: ConfigStore) -> BaseAgent:
    _ensure_registered()
    cls = AGENT_CLASSES.get(agent_id)
    if cls is None:
        raise ConfigurationError(f"Unknown agent type '{agent_id}'")
    return cls(config_store)


def describe_agents(config_store: ConfigStore) -> list[dict]:
    """保留管理员 API 使用的原有响应字段。"""
    described: list[dict] = []
    for agent_id in agent_ids():
        config = config_store.try_agent(agent_id)
        described.append(
            {
                "id": agent_id,
                "class": AGENT_CLASSES[agent_id].__name__,
                "capability": AGENT_CLASSES[agent_id].capability,
                "configured": config is not None,
                "enabled": bool(config and config.enabled),
                "provider": config.model.provider if config else "",
                "model_id": config.model.model_id if config else "",
                "config_version": config.config_version if config else "",
            }
        )
    return described
