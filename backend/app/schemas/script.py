"""Script agent I/O schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ChapterSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int
    title: str
    summary: str


class DialogueLine(BaseModel):
    model_config = ConfigDict(extra="ignore")

    character_name: str
    text: str
    emotion: str = ""
    chapter_index: int | None = None


class StoryEventDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    description: str
    chapter_index: int | None = None
    characters: list[str] = Field(default_factory=list)
    location: str = ""
    importance: float = 0.5


class ScriptInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chapters: list[dict] = Field(default_factory=list)
    language: str = "zh"
    genre: str = ""
    title_hint: str = ""


class ScriptOutput(BaseModel):
    """Structured script handed to downstream agents."""

    model_config = ConfigDict(extra="ignore")

    title: str
    logline: str = ""
    synopsis: str = ""
    genre: str = ""
    tone: str = ""
    chapters: list[ChapterSummary] = Field(default_factory=list)
    events: list[StoryEventDraft] = Field(default_factory=list)
    dialogues: list[DialogueLine] = Field(default_factory=list)
