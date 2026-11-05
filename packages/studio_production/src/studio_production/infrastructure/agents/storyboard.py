"""Storyboard Agent: splits the directing plan into structured shots."""

from __future__ import annotations

from typing import Any, ClassVar

from studio_ai_runtime.base import AgentContext, StructuredLLMAgent
from studio_production.contracts import ShotDraft, StoryboardInput, StoryboardOutput


class StoryboardAgent(StructuredLLMAgent):
    agent_id: ClassVar[str] = "storyboard"
    input_model: ClassVar[type] = StoryboardInput
    output_model: ClassVar[type] = StoryboardOutput
    schema_name: ClassVar[str] = "storyboard"

    def build_variables(self, inputs: StoryboardInput, ctx: AgentContext) -> dict[str, Any]:
        plan = inputs.plan or {}
        return {
            "script": inputs.script,
            "characters": inputs.characters,
            "scenes": inputs.scenes,
            "plan": plan,
            "shots_target": inputs.shots_target
            or int((plan.get("shot_strategy") or {}).get("total_shots") or 0),
        }

    def postprocess(
        self, output: StoryboardOutput, inputs: StoryboardInput, ctx: AgentContext
    ) -> StoryboardOutput:
        name_to_id = {
            str(character.get("name")): str(character.get("id") or "")
            for character in inputs.characters
            if character.get("name")
        }
        name_to_id.setdefault("", "")
        character_ids = {str(item.get("id")) for item in inputs.characters if item.get("id")}
        scene_names = {str(item.get("name")) for item in inputs.scenes if item.get("name")}
        style = str((inputs.plan or {}).get("visual_style") or "电影感写实风格")
        negative_default = "模糊，畸变，文字水印，多余肢体"

        shots: list[ShotDraft] = []
        for index, shot in enumerate(output.shots, start=1):
            if shot.scene_name and shot.scene_name not in scene_names:
                raise ValueError("scene_name只可引用已提供场景；没有场景档案时请留空并在description描述地点")
            shot.order = index
            shot.temp_id = shot.temp_id or f"shot_{index:03d}"
            for ref in shot.characters:
                if not ref.character_id:
                    ref.character_id = name_to_id.get(ref.character_name, "")
                if not ref.character_id or ref.character_id not in character_ids:
                    raise ValueError("characters只可引用已提供人物ID；没有人物档案时该列表必须为空")
            for line in shot.dialogue:
                if not line.character_id:
                    line.character_id = name_to_id.get(line.character_name, "")
                if line.character_id and line.character_id not in character_ids:
                    raise ValueError("dialogue.character_id不属于已提供的人物")
            if not shot.visual_prompt:
                shot.visual_prompt = (
                    f"{style}，{shot.scene_name}，{shot.description[:80]}，"
                    f"{shot.camera.shot_type}，{shot.camera.movement}"
                ).strip("，")
            if not shot.negative_prompt:
                shot.negative_prompt = negative_default
            shots.append(shot)

        # 空镜头表、空描述或非法时长由Schema拒绝并进入既有修复链路，不补占位稿冒成功。
        output.shots = shots
        output.title = output.title or str(inputs.script.get("title") or "分镜表")
        return output
