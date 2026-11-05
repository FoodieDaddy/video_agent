"""AI 执行模块公开入口。

应用用例通过这里调用现有执行协调与注册能力。审计/预算写入保持本次迁移前
的 Session 和事务契约；具体 Agent 和 Provider 位于各自内部实现目录。
"""

from studio_ai_runtime.application import execution
from studio_ai_runtime.application.execution import run_agent
from studio_ai_runtime.base import AgentContext, AgentResult, BaseAgent, MediaAgent, StructuredLLMAgent
from studio_ai_runtime.registry import AGENT_CLASSES, agent_ids, create_agent, describe_agents

__all__ = [
    "execution",
    "AGENT_CLASSES",
    "AgentContext",
    "AgentResult",
    "BaseAgent",
    "MediaAgent",
    "StructuredLLMAgent",
    "agent_ids",
    "create_agent",
    "describe_agents",
    "run_agent",
]
