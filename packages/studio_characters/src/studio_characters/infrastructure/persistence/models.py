"""Character-owned mappings for profiles, visual assets, costumes and relations."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from studio_platform.constants import CharacterStatus
from studio_platform.persistence.base import Base, TimestampMixin, id_column


class Character(Base, TimestampMixin):
    __tablename__ = "characters"

    id: Mapped[str] = id_column("char")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    role_type: Mapped[str] = mapped_column(String(32), default="supporting")
    status: Mapped[str] = mapped_column(String(32), default=CharacterStatus.DRAFT.value)
    source: Mapped[str] = mapped_column(String(32), default="extracted")  # extracted|manual|uploaded
    canonical_profile_id: Mapped[str] = mapped_column(String(48), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    appearance_keywords: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    approved_version: Mapped[int] = mapped_column(Integer, default=0)


class CharacterProfile(Base, TimestampMixin):
    """Immutable profile version: one character keeps one canonical version."""

    __tablename__ = "character_profiles"
    __table_args__ = (UniqueConstraint("character_id", "version", name="uq_character_profile"),)

    id: Mapped[str] = id_column("cprofile")
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    character_id: Mapped[str] = mapped_column(String(48), ForeignKey("characters.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32), default="ai")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_id: Mapped[str] = mapped_column(String(64), default="")
    model_id: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    config_version: Mapped[str] = mapped_column(String(32), default="")


class CharacterAsset(Base, TimestampMixin):
    __tablename__ = "character_assets"

    id: Mapped[str] = id_column("casset")
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    character_id: Mapped[str] = mapped_column(String(48), ForeignKey("characters.id"), index=True)
    asset_id: Mapped[str] = mapped_column(String(48), ForeignKey("assets.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="portrait")
    version: Mapped[int] = mapped_column(Integer, default=1)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_asset_id: Mapped[str] = mapped_column(String(48), default="")
    model_id: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    config_version: Mapped[str] = mapped_column(String(32), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class CharacterCostume(Base, TimestampMixin):
    __tablename__ = "character_costumes"

    id: Mapped[str] = id_column("costume")
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    character_id: Mapped[str] = mapped_column(String(48), ForeignKey("characters.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="default")
    description: Mapped[str] = mapped_column(Text, default="")
    story_time: Mapped[str] = mapped_column(String(120), default="")
    visual_keywords: Mapped[list] = mapped_column(JSON, default=list)
    asset_id: Mapped[str] = mapped_column(String(48), default="")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)


class CharacterState(Base, TimestampMixin):
    __tablename__ = "character_states"

    id: Mapped[str] = id_column("cstate")
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    character_id: Mapped[str] = mapped_column(String(48), ForeignKey("characters.id"), index=True)
    story_time: Mapped[str] = mapped_column(String(120), default="")
    age: Mapped[str] = mapped_column(String(64), default="")
    emotion: Mapped[str] = mapped_column(String(64), default="")
    injury: Mapped[str] = mapped_column(String(255), default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    items: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")


class CharacterRelationship(Base, TimestampMixin):
    __tablename__ = "character_relationships"

    id: Mapped[str] = id_column("crel")
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    source_character_id: Mapped[str] = mapped_column(String(48), ForeignKey("characters.id"), index=True)
    target_character_id: Mapped[str] = mapped_column(String(48), ForeignKey("characters.id"), index=True)
    relation: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    strength: Mapped[float] = mapped_column(Float, default=0.5)


class CharacterVoice(Base, TimestampMixin):
    __tablename__ = "character_voices"

    id: Mapped[str] = id_column("voice")
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    character_id: Mapped[str] = mapped_column(String(48), ForeignKey("characters.id"), index=True)
    voice_id: Mapped[str] = mapped_column(String(120), default="")
    provider: Mapped[str] = mapped_column(String(64), default="")
    model_id: Mapped[str] = mapped_column(String(128), default="")
    style: Mapped[str] = mapped_column(String(120), default="")
    sample_asset_id: Mapped[str] = mapped_column(String(48), default="")
    consent_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
