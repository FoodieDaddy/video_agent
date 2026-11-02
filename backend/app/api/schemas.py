"""Request bodies for the public API.

Only *input* models live here; responses are built by
:mod:`app.api.serializers` from service payloads so the wire format stays
stable even when the ORM changes.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    language: str = "zh"
    genre: str = ""
    aspect_ratio: str = "16:9"
    budget_limit_usd: float = 0.0
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    aspect_ratio: str | None = None
    budget_limit_usd: float | None = None
    settings: dict[str, Any] | None = None


class ScriptUpdate(BaseModel):
    title: str | None = None
    logline: str | None = None
    synopsis: str | None = None
    content: dict[str, Any] | None = None
    status: str | None = None


class CharacterUpdate(BaseModel):
    name: str | None = None
    summary: str | None = None
    appearance_keywords: list[str] | None = None
    profile: dict[str, Any] | None = None


class CharacterImagesRequest(BaseModel):
    kinds: list[str] = Field(default_factory=lambda: ["portrait", "full_body", "turnaround"])


class SceneUpdate(BaseModel):
    name: str | None = None
    summary: str | None = None
    profile: dict[str, Any] | None = None


class ShotUpdate(BaseModel):
    description: str | None = None
    action: str | None = None
    camera: dict[str, Any] | None = None
    dialogue: list[dict[str, Any]] | None = None
    duration_seconds: float | None = Field(default=None, gt=0, le=60)
    visual_prompt: str | None = None
    negative_prompt: str | None = None
    scene_id: str | None = None


class ReviewDecision(BaseModel):
    status: Literal["approved", "rejected"]
    comment: str = ""
    decision: dict[str, Any] = Field(default_factory=dict)
    resume_workflow: bool = True


class ReviewCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class WorkflowStart(BaseModel):
    workflow_id: str | None = None


class ConfigVersionCreate(BaseModel):
    payload: dict[str, Any]
    note: str = ""
