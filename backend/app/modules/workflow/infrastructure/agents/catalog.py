"""工作流协调领域 Agent 的模块内注册表。"""

from app.modules.ai_runtime.base import BaseAgent

from .orchestrator import OrchestratorAgent

AGENTS: dict[str, type[BaseAgent]] = {"orchestrator": OrchestratorAgent}
