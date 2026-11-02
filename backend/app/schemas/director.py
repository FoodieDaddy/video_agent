"""Director agent I/O schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ShotStrategy(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_shots: int = 6
    avg_duration_seconds: float = 5.0
    pacing_notes: str = ""
    coverage_notes: str = ""


class DirectingPlanInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    script: dict = Field(default_factory=dict)
    characters: list[dict] = Field(default_factory=list)
    scenes: list[dict] = Field(default_factory=list)
    genre: str = ""
    shots_target: int = 6


class DirectingPlanOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    visual_style: str
    color_palette: list[str] = Field(default_factory=list)
    lighting_style: str = ""
    camera_language: str = ""
    pacing: str = ""
    narrative_arc: str = ""
    shot_strategy: ShotStrategy = Field(default_factory=ShotStrategy)
    continuity_rules: list[str] = Field(default_factory=list)
    scenes_order: list[str] = Field(default_factory=list)
    notes: str = ""
