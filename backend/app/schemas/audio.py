"""Audio agent I/O schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class VoiceLineDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    line_id: str
    character_name: str = ""
    text: str
    emotion: str = ""
    duration_seconds: float = 0.0
    shot_id: str = ""


class AudioPlanInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shots: list[dict] = Field(default_factory=list)
    synopsis: str = ""
    language: str = "zh"
    style: str = ""


class AudioPlanOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    narration: str = ""
    voice_lines: list[VoiceLineDraft] = Field(default_factory=list)
    music_cue: str = ""
    sfx_cues: list[str] = Field(default_factory=list)
