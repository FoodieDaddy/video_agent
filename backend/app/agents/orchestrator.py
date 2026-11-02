"""Orchestrator Agent.

Produces a *plan* (ordered nodes + review stages) rather than executing it: the
workflow engine owns execution, persistence and human gates, while the agent
decides what the plan for this particular project should be.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.agents.base import AgentContext, StructuredLLMAgent
from app.schemas.orchestrator import OrchestratorInput, OrchestratorPlan, WorkflowPlanNode

_DEFAULT_NODES = [
    ("analyze_script", "解析章节并生成结构化剧本", "script"),
    ("extract_characters", "提取人物与人物关系", "character_extraction"),
    ("extract_scenes", "提取场景并生成场景描述", "scene_extraction"),
    ("direct", "制定导演规划", "director"),
    ("storyboard", "拆解镜头表", "storyboard"),
    ("generate_assets", "生成角色形象资产", "character_image"),
    ("generate_shots", "生成镜头视频", "video"),
    ("generate_audio", "生成配音与字幕", "audio"),
    ("edit", "剪辑合成", "editing"),
    ("evaluate", "质量评估", "evaluation"),
]


class OrchestratorAgent(StructuredLLMAgent):
    agent_id: ClassVar[str] = "orchestrator"
    input_model: ClassVar[type] = OrchestratorInput
    output_model: ClassVar[type] = OrchestratorPlan
    schema_name: ClassVar[str] = "orchestrator_plan"

    def build_variables(self, inputs: OrchestratorInput, ctx: AgentContext) -> dict[str, Any]:
        return {
            "objective": inputs.objective,
            "project": inputs.project,
            "constraints": inputs.constraints,
            "workflow_id": ctx.extra.get("workflow_id", ""),
        }

    def postprocess(
        self, output: OrchestratorPlan, inputs: OrchestratorInput, ctx: AgentContext
    ) -> OrchestratorPlan:
        known = {node.node_id for node in output.nodes}
        for node_id, purpose, agent in _DEFAULT_NODES:
            if node_id not in known:
                output.nodes.append(WorkflowPlanNode(node_id=node_id, purpose=purpose, agent=agent))
        if not output.review_stages:
            output.review_stages = ["characters_scenes", "storyboard", "shots", "final"]
        output.objective = output.objective or inputs.objective
        return output
