"""Users, projects, project membership, media assets and configuration versions."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import ProjectStatus
from app.models.base import Base, TimestampMixin, id_column


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = id_column("user")
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(32), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = id_column("proj")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[str] = mapped_column(String(48), ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=ProjectStatus.DRAFT.value)
    language: Mapped[str] = mapped_column(String(16), default="zh")
    genre: Mapped[str] = mapped_column(String(64), default="")
    aspect_ratio: Mapped[str] = mapped_column(String(16), default="16:9")
    budget_limit_usd: Mapped[float] = mapped_column(Float, default=0.0)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    config_version: Mapped[str] = mapped_column(String(64), default="")


class ProjectMember(Base, TimestampMixin):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    id: Mapped[str] = id_column("member")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(48), ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="editor")


class Asset(Base, TimestampMixin):
    """Every generated or uploaded media file is an immutable asset row."""

    __tablename__ = "assets"

    id: Mapped[str] = id_column("asset")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int | None] = mapped_column(nullable=True)
    height: Mapped[int | None] = mapped_column(nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    model_id: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    config_version: Mapped[str] = mapped_column(String(32), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(48), default="")


class ConfigVersion(Base, TimestampMixin):
    """Immutable history for runtime configuration changes (admin console)."""

    __tablename__ = "config_versions"
    __table_args__ = (UniqueConstraint("scope", "key", "version", name="uq_config_version"),)

    id: Mapped[str] = id_column("cfgver")
    scope: Mapped[str] = mapped_column(String(32), index=True)  # agent | provider | workflow
    key: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(default=1)
    checksum: Mapped[str] = mapped_column(String(32), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(48), default="")
    note: Mapped[str] = mapped_column(Text, default="")


class PromptVersion(Base, TimestampMixin):
    """Prompt template snapshot, recorded the first time a version is used."""

    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_prompt_version"),)

    id: Mapped[str] = id_column("prompt")
    name: Mapped[str] = mapped_column(String(200), index=True)
    version: Mapped[str] = mapped_column(String(32))
    checksum: Mapped[str] = mapped_column(String(32), default="")
    content: Mapped[str] = mapped_column(Text, default="")


class BudgetEvent(Base, TimestampMixin):
    """Cost ledger: one row per priced model/media call."""

    __tablename__ = "budget_events"

    id: Mapped[str] = id_column("budget")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    category: Mapped[str] = mapped_column(String(32), default="llm")
    amount_usd: Mapped[float] = mapped_column(Float, default=0.0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
