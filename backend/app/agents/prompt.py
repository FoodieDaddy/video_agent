"""Prompt Agent: converts a structured shot into a video-model prompt pack."""

from __future__ import annotations

from typing import Any, ClassVar

from app.agents.base import AgentContext, StructuredLLMAgent
from app.schemas.prompt import PromptInput, PromptPack


class PromptAgent(StructuredLLMAgent):
    agent_id: ClassVar[str] = "prompt"
    input_model: ClassVar[type] = PromptInput
    output_model: ClassVar[type] = PromptPack
    schema_name: ClassVar[str] = "prompt_pack"

    def build_variables(self, inputs: PromptInput, ctx: AgentContext) -> dict[str, Any]:
        shot = inputs.shot or {}
        return {
            "shot": shot,
            "visual_style": inputs.visual_style,
            "continuity_rules": inputs.continuity_rules,
            "platform": inputs.platform,
            "shot_id": shot.get("shot_id") or shot.get("temp_id") or "",
            "scene_name": shot.get("scene_name", ""),
        }

    def postprocess(self, output: PromptPack, inputs: PromptInput, ctx: AgentContext) -> PromptPack:
        shot = inputs.shot or {}
        if not output.visual_prompt:
            output.visual_prompt = str(
                shot.get("visual_prompt") or shot.get("description") or "电影感写实画面"
            )
        if not output.negative_prompt:
            output.negative_prompt = str(shot.get("negative_prompt") or "模糊，畸变，文字水印")
        if not output.style_tokens:
            output.style_tokens = ["cinematic", "film grain", "high detail"]
        if not output.camera_tokens:
            camera = shot.get("camera") or {}
            output.camera_tokens = [
                str(camera.get("shot_type") or "medium_shot"),
                str(camera.get("movement") or "static"),
            ]
        if not output.character_tokens:
            output.character_tokens = [
                str(item.get("character_name"))
                for item in shot.get("characters") or []
                if item.get("character_name")
            ]
        return output
