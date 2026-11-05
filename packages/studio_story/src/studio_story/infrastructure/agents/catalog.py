"""故事与剧本领域 Agent 的模块内注册表。"""

from studio_ai_runtime.base import BaseAgent

from .script import ScriptAgent

AGENTS: dict[str, type[BaseAgent]] = {"script": ScriptAgent}
