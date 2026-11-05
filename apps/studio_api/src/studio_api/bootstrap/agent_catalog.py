"""应用组合根：汇总各业务模块声明的 Agent，不承载 Agent 实现。

每个业务模块维护自己的 infrastructure/agents/catalog.py。
ai_runtime 只负责注册和执行，不反向依赖具体业务 Agent。
"""

from __future__ import annotations

from studio_ai_runtime.base import BaseAgent
from studio_ai_runtime.registry import configure_default_agent_loader

# 兼容原有的角色分组标识；它表达产品角色，不是动态调度策略。
AGENT_FAMILIES: dict[str, tuple[str, ...]] = {
    "orchestrator": ("orchestrator",),
    "script": ("script",),
    "character": ("character_extraction", "character_description", "character_consistency"),
    "character_vision": ("character_vision",),
    "character_image": ("character_image",),
    "scene": ("scene_extraction", "scene_description"),
    "director": ("director",),
    "storyboard": ("storyboard",),
    "prompt": ("prompt",),
    "video": ("video",),
    "audio": ("audio", "audio_voice"),
    "editing": ("editing",),
    "evaluation": ("evaluation",),
}


def builtin_agent_classes() -> dict[str, type[BaseAgent]]:
    """从业务模块收集 Agent；重复执行 ID 会在启动时显式失败。"""
    from studio_characters.infrastructure.agents.catalog import AGENTS as character_agents
    from studio_production.infrastructure.agents.catalog import AGENTS as production_agents
    from studio_scenes.infrastructure.agents.catalog import AGENTS as scene_agents
    from studio_story.infrastructure.agents.catalog import AGENTS as story_agents
    from studio_workflow.infrastructure.agents.catalog import AGENTS as workflow_agents

    catalogs = (
        workflow_agents,
        story_agents,
        character_agents,
        scene_agents,
        production_agents,
    )
    result: dict[str, type[BaseAgent]] = {}
    for catalog in catalogs:
        overlap = result.keys() & catalog.keys()
        if overlap:
            raise RuntimeError(f"Duplicate Agent IDs declared by business modules: {sorted(overlap)}")
        result.update(catalog)
    return result


def register_agents() -> None:
    """正常启动与兼容惰性调用共用此装配函数。"""
    from studio_ai_runtime.registry import register_agent_classes

    register_agent_classes(builtin_agent_classes())


# 应用声明默认装配；独立 ai_runtime 不依赖本文件。
configure_default_agent_loader(register_agents)
