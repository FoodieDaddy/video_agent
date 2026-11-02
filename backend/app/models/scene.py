"""Scenes and scene reference assets."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, id_column


class Scene(Base, TimestampMixin):
    __tablename__ = "scenes"

    id: Mapped[str] = id_column("scene")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    slug: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    summary: Mapped[str] = mapped_column(Text, default="")
    canonical_profile_id: Mapped[str] = mapped_column(String(48), default="")
    approved_version: Mapped[int] = mapped_column(Integer, default=0)
    chapter_index: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SceneProfile(Base, TimestampMixin):
    __tablename__ = "scene_profiles"
    __table_args__ = (UniqueConstraint("scene_id", "version", name="uq_scene_profile"),)

    id: Mapped[str] = id_column("sprofile")
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    scene_id: Mapped[str] = mapped_column(String(48), ForeignKey("scenes.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_id: Mapped[str] = mapped_column(String(64), default="")
    model_id: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    config_version: Mapped[str] = mapped_column(String(32), default="")


class SceneAsset(Base, TimestampMixin):
    __tablename__ = "scene_assets"

    id: Mapped[str] = id_column("sasset")
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    scene_id: Mapped[str] = mapped_column(String(48), ForeignKey("scenes.id"), index=True)
    asset_id: Mapped[str] = mapped_column(String(48), ForeignKey("assets.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="reference")
    version: Mapped[int] = mapped_column(Integer, default=1)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    model_id: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    config_version: Mapped[str] = mapped_column(String(32), default="")
