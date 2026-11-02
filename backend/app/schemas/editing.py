"""Editing agent I/O schemas (timeline model consumed by the FFmpeg renderer)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TimelineClip(BaseModel):
    model_config = ConfigDict(extra="ignore")

    clip_id: str
    shot_id: str
    order: int = 0
    start: float = 0.0
    duration: float = 0.0
    video_asset_id: str | None = None
    audio_asset_id: str | None = None
    transition: str = "cut"


class EditingPlanInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shots: list[dict] = Field(default_factory=list)
    visual_style: str = ""
    width: int = 1280
    height: int = 720
    fps: int = 25


class EditingPlanOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timeline: list[TimelineClip] = Field(default_factory=list)
    subtitles: bool = True
    total_duration: float = 0.0
    notes: str = ""
