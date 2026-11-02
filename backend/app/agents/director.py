"""Director Agent: turns the approved script into a global directing plan."""

from __future__ import annotations

from typing import Any, ClassVar

from app.agents.base import AgentContext, StructuredLLMAgent
from app.schemas.director import DirectingPlanInput, DirectingPlanOutput


class DirectorAgent(StructuredLLMAgent):
    agent_id: ClassVar[str] = "director"
    input_model: ClassVar[type] = DirectingPlanInput
    output_model: ClassVar[type] = DirectingPlanOutput
    schema_name: ClassVar[str] = "directing_plan"

    def build_variables(self, inputs: DirectingPlanInput, ctx: AgentContext) -> dict[str, Any]:
        return {
            "script": inputs.script,
            "characters": inputs.characters,
            "scenes": inputs.scenes,
            "genre": inputs.genre or str(inputs.script.get("genre") or ""),
            "shots_target": inputs.shots_target,
            "character_count": len(inputs.characters),
            "scene_count": len(inputs.scenes),
        }

    def postprocess(
        self, output: DirectingPlanOutput, inputs: DirectingPlanInput, ctx: AgentContext
    ) -> DirectingPlanOutput:
        if not output.visual_style:
            output.visual_style = "电影感写实风格，克制的色调与稳定的机位语言"
        if not output.shot_strategy.total_shots:
            output.shot_strategy.total_shots = max(1, inputs.shots_target)
        if not output.shot_strategy.avg_duration_seconds:
            output.shot_strategy.avg_duration_seconds = 5.0
        if not output.scenes_order:
            output.scenes_order = [
                str(scene.get("name")) for scene in inputs.scenes if scene.get("name")
            ]
        if not output.continuity_rules:
            output.continuity_rules = [
                "同一场景内光线方向保持一致",
                "角色服装与已批准的人物档案一致",
                "相邻镜头遵循 180 度轴线规则",
            ]
        return output
