"""Editing Agent: builds the timeline consumed by the FFmpeg renderer."""

from __future__ import annotations

from typing import Any, ClassVar

from studio_ai_runtime.base import AgentContext, StructuredLLMAgent
from studio_production.contracts import EditingPlanInput, EditingPlanOutput, TimelineClip


class EditingAgent(StructuredLLMAgent):
    agent_id: ClassVar[str] = "editing"
    input_model: ClassVar[type] = EditingPlanInput
    output_model: ClassVar[type] = EditingPlanOutput
    schema_name: ClassVar[str] = "editing_plan"

    def build_variables(self, inputs: EditingPlanInput, ctx: AgentContext) -> dict[str, Any]:
        return {
            "shots": inputs.shots,
            "visual_style": inputs.visual_style,
            "width": inputs.width,
            "height": inputs.height,
            "fps": inputs.fps,
        }

    def postprocess(
        self, output: EditingPlanOutput, inputs: EditingPlanInput, ctx: AgentContext
    ) -> EditingPlanOutput:
        shot_by_id = {str(shot.get("shot_id") or ""): shot for shot in inputs.shots}
        ordered = sorted(output.timeline, key=lambda clip: clip.order)
        timeline: list[TimelineClip] = []
        cursor = 0.0
        for index, clip in enumerate(ordered, start=1):
            shot = shot_by_id.get(clip.shot_id, {})
            if not clip.shot_id and inputs.shots:
                shot = inputs.shots[min(index - 1, len(inputs.shots) - 1)]
                clip.shot_id = str(shot.get("shot_id") or "")
            if not clip.duration or clip.duration <= 0:
                clip.duration = float(shot.get("duration_seconds") or 5.0)
            clip.order = index
            clip.start = round(cursor, 3)
            clip.clip_id = clip.clip_id or f"clip_{index:03d}"
            if not clip.video_asset_id:
                clip.video_asset_id = shot.get("video_asset_id") or None
            if not clip.audio_asset_id:
                clip.audio_asset_id = shot.get("audio_asset_id") or None
            timeline.append(clip)
            cursor += clip.duration

        if not timeline and inputs.shots:
            for index, shot in enumerate(inputs.shots, start=1):
                duration = float(shot.get("duration_seconds") or 5.0)
                timeline.append(
                    TimelineClip(
                        clip_id=f"clip_{index:03d}",
                        shot_id=str(shot.get("shot_id") or ""),
                        order=index,
                        start=round(cursor, 3),
                        duration=duration,
                        video_asset_id=shot.get("video_asset_id") or None,
                        audio_asset_id=shot.get("audio_asset_id") or None,
                        transition="cut" if index > 1 else "fade_in",
                    )
                )
                cursor += duration

        output.timeline = timeline
        output.total_duration = round(cursor, 3)
        if not output.notes:
            output.notes = (
                f"{len(timeline)} 个镜头按叙事顺序排列，目标 {inputs.width}x{inputs.height}@{inputs.fps}fps。"
            )
        return output
