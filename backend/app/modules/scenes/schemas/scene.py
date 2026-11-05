"""Scene agent I/O schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SceneCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    chapter_index: int | None = None
    time_of_day: str = ""
    environment: str = ""
    architecture: str = ""
    lighting: str = ""
    mood: str = ""
    evidence: str = ""


class SceneExtractionInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chapter_texts: list[dict] = Field(default_factory=list)
    script: dict = Field(default_factory=dict)


class SceneExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scenes: list[SceneCandidate] = Field(default_factory=list)


class SceneDescriptionInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    evidence: str = ""
    time_of_day: str = ""
    mood: str = ""
    architecture: str = ""


class SceneProfileOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str
    time_of_day: str = ""
    environment: str = ""
    architecture: str = ""
    lighting: str = ""
    mood: str = ""
    palette: list[str] = Field(default_factory=list)
    props: list[str] = Field(default_factory=list)
    visual_prompt: str = ""
    negative_prompt: str = ""
