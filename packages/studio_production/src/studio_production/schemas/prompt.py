"""Prompt agent I/O schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PromptInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shot: dict = Field(default_factory=dict)
    visual_style: str = ""
    continuity_rules: list[str] = Field(default_factory=list)
    platform: str = "video_model"


class PromptPack(BaseModel):
    model_config = ConfigDict(extra="ignore")

    visual_prompt: str
    negative_prompt: str = ""
    style_tokens: list[str] = Field(default_factory=list)
    camera_tokens: list[str] = Field(default_factory=list)
    character_tokens: list[str] = Field(default_factory=list)
