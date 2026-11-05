"""Evaluation agent I/O schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EvaluationIssue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    severity: str = "medium"
    description: str = ""


class EvaluationInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stage: str = "final"
    metrics: dict = Field(default_factory=dict)
    project_summary: dict = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(default_factory=dict)


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shot_id: str | None = None
    overall_score: float = 0.0
    scores: dict[str, float] = Field(default_factory=dict)
    issues: list[EvaluationIssue] = Field(default_factory=list)
    recommendation: str = "review"
    summary: str = ""
