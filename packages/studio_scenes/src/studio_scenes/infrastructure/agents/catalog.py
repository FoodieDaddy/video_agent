"""场景领域 Agent 的模块内注册表。"""

from studio_ai_runtime.base import BaseAgent

from .scene import SceneDescriptionAgent, SceneExtractionAgent

AGENTS: dict[str, type[BaseAgent]] = {
    "scene_extraction": SceneExtractionAgent,
    "scene_description": SceneDescriptionAgent,
}
