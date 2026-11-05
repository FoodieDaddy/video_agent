"""Request bodies for the public API.

Only *input* models live here; responses are built by
:mod:`app.api.serializers` from service payloads so the wire format stays
stable even when the ORM changes.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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


class ScriptVersionCreate(BaseModel):
    """新建或另存剧本版本；已有稿件必须提供当前基线，正文不自动去除空白。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    script_text: str = Field(min_length=1, max_length=200_000)
    logline: str = Field(default="", max_length=10_000)
    synopsis: str = Field(default="", max_length=50_000)
    base_script_id: str | None = Field(default=None, max_length=48)


class ScriptRestoreRequest(BaseModel):
    """恢复操作复制历史为新版本，不移动或覆盖历史行。"""

    model_config = ConfigDict(extra="forbid")

    base_script_id: str = Field(min_length=1, max_length=48)


class ScriptAssistRequest(BaseModel):
    """AI 只基于已保存版本执行；续写拼接由应用用例负责。"""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["polish", "continue"]
    base_script_id: str = Field(min_length=1, max_length=48)
    instruction: str = Field(default="", max_length=8000)


class CharacterUpdate(BaseModel):
    name: str | None = None
    summary: str | None = None
    appearance_keywords: list[str] | None = None
    profile: dict[str, Any] | None = None


class DirectingRequest(BaseModel):
    """可选导演创作要求；无请求体沿用项目默认值，显式基线用于拒绝旧稿任务。"""

    model_config = ConfigDict(extra="forbid")

    base_script_id: str | None = Field(default=None, min_length=1, max_length=48)
    instruction: str = Field(default="", max_length=8000)
    shots_target: int | None = Field(default=None, ge=1, le=120, strict=True)


class CharacterImagesRequest(BaseModel):
    kinds: list[str] = Field(default_factory=lambda: ["portrait", "full_body", "turnaround"])


class SceneUpdate(BaseModel):
    name: str | None = None
    summary: str | None = None
    profile: dict[str, Any] | None = None


class ShotUpdate(BaseModel):
    base_storyboard_id: str | None = Field(default=None, min_length=1, max_length=48)
    base_shot_fingerprint: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    action: str | None = None
    camera: dict[str, Any] | None = None
    dialogue: list[dict[str, Any]] | None = None
    duration_seconds: float | None = Field(default=None, gt=0, le=60)
    visual_prompt: str | None = None
    negative_prompt: str | None = None
    scene_id: str | None = None


class StoryboardRequest(BaseModel):
    """分镜仅绑定当前剧本和导演版本；旧无请求体入口仍深化提示词。"""

    model_config = ConfigDict(extra="forbid")

    base_script_id: str | None = Field(default=None, min_length=1, max_length=48)
    base_plan_id: str | None = Field(default=None, min_length=1, max_length=48)
    refine_prompts: bool = Field(default=True, strict=True)


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
