"""导演 Agent：根据实际提供的剧本与档案规划风格，不代替人工审核。"""

from __future__ import annotations

from typing import Any, ClassVar

from app.modules.ai_runtime.base import AgentContext, StructuredLLMAgent
from app.modules.production.contracts import DirectingPlanInput, DirectingPlanOutput


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
            "instruction": inputs.instruction,
            "character_count": len(inputs.characters),
            "scene_count": len(inputs.scenes),
        }

    def postprocess(
        self, output: DirectingPlanOutput, inputs: DirectingPlanInput, ctx: AgentContext
    ) -> DirectingPlanOutput:
        # 空风格、非法数量和时长应走 Schema 修复／失败链路，不能补一段通用风格
        # 冒充有效模型产物。下面只保留旧协议中可由已知输入推导的顺序与通用约束。
        if not output.scenes_order:
            output.scenes_order = [str(scene.get("name")) for scene in inputs.scenes if scene.get("name")]
        if not output.continuity_rules:
            output.continuity_rules = [
                "同一场景内光线方向保持一致",
                "人物出现时保持所提供档案中的外观与服装约束",
                "相邻镜头遵循 180 度轴线规则",
            ]
        return output
