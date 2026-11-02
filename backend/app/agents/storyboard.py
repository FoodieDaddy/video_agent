"""Storyboard Agent: splits the directing plan into structured shots."""

from __future__ import annotations

from typing import Any, ClassVar

from app.agents.base import AgentContext, StructuredLLMAgent
from app.schemas.storyboard import ShotDraft, StoryboardInput, StoryboardOutput


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
        style = str((inputs.plan or {}).get("visual_style") or "电影感写实风格")
        negative_default = "模糊，畸变，文字水印，多余肢体"

        shots: list[ShotDraft] = []
        for index, shot in enumerate(output.shots, start=1):
            shot.order = index
            shot.temp_id = shot.temp_id or f"shot_{index:03d}"
            if not shot.duration_seconds or shot.duration_seconds <= 0:
                shot.duration_seconds = 5.0
            shot.duration_seconds = min(15.0, shot.duration_seconds)
            for ref in shot.characters:
                if not ref.character_id:
                    ref.character_id = name_to_id.get(ref.character_name, "")
            for line in shot.dialogue:
                if not line.character_id:
                    line.character_id = name_to_id.get(line.character_name, "")
            if not shot.visual_prompt:
                shot.visual_prompt = (
                    f"{style}，{shot.scene_name}，{shot.description[:80]}，"
                    f"{shot.camera.shot_type}，{shot.camera.movement}"
                ).strip("，")
            if not shot.negative_prompt:
                shot.negative_prompt = negative_default
            shots.append(shot)

        if not shots:
            shots.append(
                ShotDraft(
                    temp_id="shot_001",
                    order=1,
                    description="模型未产出镜头，占位镜头待人工补充",
                    duration_seconds=5.0,
                    visual_prompt=f"{style}，{inputs.script.get('title', '故事')}开场画面",
                    negative_prompt=negative_default,
                )
            )

        output.shots = shots
        output.title = output.title or str(inputs.script.get("title") or "分镜表")
        return output
