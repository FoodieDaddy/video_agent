"""Evaluation Agent: scores each pipeline stage and recommends accept/retry."""

from __future__ import annotations

from typing import Any, ClassVar

from app.agents.base import AgentContext, StructuredLLMAgent
from app.schemas.evaluation import EvaluationInput, EvaluationIssue, EvaluationReport

_DEFAULT_THRESHOLDS = {
    "story_consistency": 0.75,
    "character_consistency": 0.75,
    "scene_consistency": 0.7,
    "motion_quality": 0.65,
    "visual_quality": 0.7,
    "audio_quality": 0.65,
}


class EvaluationAgent(StructuredLLMAgent):
    agent_id: ClassVar[str] = "evaluation"
    input_model: ClassVar[type] = EvaluationInput
    output_model: ClassVar[type] = EvaluationReport
    schema_name: ClassVar[str] = "evaluation"

    def build_variables(self, inputs: EvaluationInput, ctx: AgentContext) -> dict[str, Any]:
        return {
            "stage": inputs.stage,
            "metrics": inputs.metrics,
            "project_summary": inputs.project_summary,
            "thresholds": inputs.thresholds or _DEFAULT_THRESHOLDS,
            "shot_id": inputs.metrics.get("shot_id") or inputs.project_summary.get("shot_id"),
        }

    def postprocess(
        self, output: EvaluationReport, inputs: EvaluationInput, ctx: AgentContext
    ) -> EvaluationReport:
        thresholds = {**_DEFAULT_THRESHOLDS, **(self.config.evaluation.thresholds or {}), **inputs.thresholds}
        shot_id = inputs.metrics.get("shot_id") or inputs.project_summary.get("shot_id")
        output.shot_id = output.shot_id or (str(shot_id) if shot_id else None)

        for name, value in list(output.scores.items()):
            limit = thresholds.get(name)
            if limit is None or not value:
                continue
            if value < limit:
                output.issues.append(
                    EvaluationIssue(
                        type=f"{name}_below_threshold",
                        severity="high" if value < limit - 0.1 else "medium",
                        description=f"{name}={value:.2f} 低于阈值 {limit:.2f}",
                    )
                )

        has_blocker = any(issue.severity == "high" for issue in output.issues)
        if output.overall_score >= 0.8 and not has_blocker:
            output.recommendation = "accept"
        elif output.overall_score < 0.5 or has_blocker:
            output.recommendation = "regenerate"
        else:
            output.recommendation = "review"

        if not output.summary:
            output.summary = (
                f"{inputs.stage} 阶段评估：整体 {output.overall_score:.2f}，"
                f"建议 {output.recommendation}。"
            )
        return output
