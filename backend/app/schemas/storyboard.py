"""Storyboard agent I/O schemas (mirrors the structured shot document)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CameraSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shot_type: str = "medium_shot"
    movement: str = "static"
    angle: str = "eye_level"
    lens: str = ""


class ShotCharacterRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    character_id: str = ""
    character_name: str = ""
    costume_id: str | None = None
    state_id: str | None = None
    action: str = ""
    emotion: str = ""


class ShotDialogue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    character_id: str = ""
    character_name: str = ""
    text: str
    emotion: str = ""


class ShotDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    temp_id: str = ""
    scene_name: str = ""
    order: int = 0
    description: str = ""
    characters: list[ShotCharacterRef] = Field(default_factory=list)
    camera: CameraSpec = Field(default_factory=CameraSpec)
    duration_seconds: float = 5.0
    dialogue: list[ShotDialogue] = Field(default_factory=list)
    action: str = ""
    visual_prompt: str = ""
    negative_prompt: str = ""
    reference_asset_ids: list[str] = Field(default_factory=list)


class StoryboardInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    script: dict = Field(default_factory=dict)
    characters: list[dict] = Field(default_factory=list)
    scenes: list[dict] = Field(default_factory=list)
    plan: dict = Field(default_factory=dict)
    shots_target: int = 6


class StoryboardOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    shots: list[ShotDraft] = Field(default_factory=list)
    notes: str = ""
