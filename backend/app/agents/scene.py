"""Scene Agent: scene extraction plus per-scene visual description."""

from __future__ import annotations

import re
from typing import Any, ClassVar

from app.agents.base import AgentContext, StructuredLLMAgent
from app.schemas.scene import (
    SceneCandidate,
    SceneDescriptionInput,
    SceneExtractionInput,
    SceneExtractionOutput,
    SceneProfileOutput,
)


class SceneExtractionAgent(StructuredLLMAgent):
    agent_id: ClassVar[str] = "scene_extraction"
    input_model: ClassVar[type] = SceneExtractionInput
    output_model: ClassVar[type] = SceneExtractionOutput
    schema_name: ClassVar[str] = "scene_extraction"

    def build_variables(self, inputs: SceneExtractionInput, ctx: AgentContext) -> dict[str, Any]:
        return {
            "chapter_texts": inputs.chapter_texts,
            "script": inputs.script,
            "chapter_count": len(inputs.chapter_texts),
        }

    def postprocess(
        self, output: SceneExtractionOutput, inputs: SceneExtractionInput, ctx: AgentContext
    ) -> SceneExtractionOutput:
        seen: set[str] = set()
        scenes: list[SceneCandidate] = []
        for scene in output.scenes:
            name = (scene.name or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            scenes.append(scene)
        if not scenes:
            scenes.append(
                SceneCandidate(
                    name="主场景",
                    chapter_index=1,
                    environment="模型未识别出明确场景，按单一主场景处理",
                    evidence="",
                )
            )
        return SceneExtractionOutput(scenes=scenes[:8])


class SceneDescriptionAgent(StructuredLLMAgent):
    agent_id: ClassVar[str] = "scene_description"
    input_model: ClassVar[type] = SceneDescriptionInput
    output_model: ClassVar[type] = SceneProfileOutput
    schema_name: ClassVar[str] = "scene_profile"

    def build_variables(self, inputs: SceneDescriptionInput, ctx: AgentContext) -> dict[str, Any]:
        return {
            "name": inputs.name,
            "evidence": inputs.evidence,
            "time_of_day": inputs.time_of_day,
            "mood": inputs.mood,
            "architecture": inputs.architecture,
        }

    def postprocess(
        self, output: SceneProfileOutput, inputs: SceneDescriptionInput, ctx: AgentContext
    ) -> SceneProfileOutput:
        output.name = output.name or inputs.name
        if not output.time_of_day:
            output.time_of_day = inputs.time_of_day or "白天"
        if not output.mood:
            output.mood = inputs.mood or "平静"
        if not output.description:
            output.description = _compact(inputs.evidence) or f"{inputs.name}的基础场景描述。"
        if not output.visual_prompt:
            output.visual_prompt = (
                f"{output.name}，{output.time_of_day}，{output.description[:120]}，"
                "电影感画面，宽银幕构图"
            )
        if not output.negative_prompt:
            output.negative_prompt = "低清晰度，文字水印，畸形结构"
        return output


def _compact(text: str, limit: int = 160) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    return clean[:limit]
