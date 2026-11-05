"""Character agent I/O schemas (extraction, description, vision, consistency)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RelationshipDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str
    target: str
    relation: str
    description: str = ""


class CharacterCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    aliases: list[str] = Field(default_factory=list)
    role_hint: str = "supporting"
    gender_hint: str = ""
    age_hint: str = ""
    evidence: str = ""


class CharacterExtractionInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    script: dict = Field(default_factory=dict)
    chapter_texts: list[dict] = Field(default_factory=list)
    language: str = "zh"


class CharacterExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    characters: list[CharacterCandidate] = Field(default_factory=list)
    relationships: list[RelationshipDraft] = Field(default_factory=list)


class CharacterDescriptionInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    evidence: list[str] = Field(default_factory=list)
    chapter_texts: list[dict] = Field(default_factory=list)
    script: dict = Field(default_factory=dict)
    language: str = "zh"


class CharacterProfileOutput(BaseModel):
    """Canonical character profile. Facts and inferences stay separated."""

    model_config = ConfigDict(extra="ignore")

    name: str
    aliases: list[str] = Field(default_factory=list)
    gender: str = "unknown"
    age_range: str = ""
    role_type: str = "supporting"
    appearance: str = ""
    hairstyle: str = ""
    body: str = ""
    clothing_default: str = ""
    personality: list[str] = Field(default_factory=list)
    background: str = ""
    motivation: str = ""
    speech_style: str = ""
    visual_keywords: list[str] = Field(default_factory=list)
    source_facts: list[str] = Field(default_factory=list)
    inferred_items: list[str] = Field(default_factory=list)


class CharacterVisionInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    image_bytes: bytes | None = None
    image_mime: str = "image/png"
    filename: str = ""
    known_name: str = ""
    known_description: str = ""


class CharacterVisionOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str
    gender: str = "unknown"
    age_range: str = ""
    hair: str = ""
    face: str = ""
    body: str = ""
    clothing: str = ""
    accessories: list[str] = Field(default_factory=list)
    visual_keywords: list[str] = Field(default_factory=list)
    confidence: float = 0.5


class ConsistencyIssue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    severity: str = "medium"
    description: str = ""


class CharacterConsistencyOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    character_id: str = ""
    overall_score: float = 0.8
    checked_assets: int = 0
    issues: list[ConsistencyIssue] = Field(default_factory=list)
    recommendation: str = "accept"
