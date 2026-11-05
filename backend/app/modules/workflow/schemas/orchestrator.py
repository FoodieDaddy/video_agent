"""Orchestrator agent I/O schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class WorkflowPlanNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    node_id: str
    purpose: str = ""
    agent: str = ""


class OrchestratorInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    objective: str = "把小说制作成短视频"
    project: dict = Field(default_factory=dict)
    constraints: dict = Field(default_factory=dict)


class OrchestratorPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    objective: str
    nodes: list[WorkflowPlanNode] = Field(default_factory=list)
    review_stages: list[str] = Field(default_factory=list)
    notes: str = ""
