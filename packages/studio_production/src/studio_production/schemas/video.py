"""Video agent I/O schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ShotVideoInput(BaseModel):
    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    shot_id: str
    prompt: str
    negative_prompt: str = ""
    duration_seconds: float = 5.0
    width: int = 1280
    height: int = 720
    aspect_ratio: str = "16:9"
    reference_image: bytes | None = None
    first_frame: bytes | None = None
    last_frame: bytes | None = None
    provider_options: dict = Field(default_factory=dict)
    extra: dict = Field(default_factory=dict)


class ShotVideoOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shot_id: str
    duration_seconds: float = 0.0
    provider: str = ""
    model_id: str = ""
    task_ref: str = ""
    cost_usd: float = 0.0
    placeholder: bool = False
