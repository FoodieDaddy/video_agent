"""Project and membership ORM mappings."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.platform.constants import ProjectStatus
from app.modules.platform.persistence.base import Base, TimestampMixin, id_column


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
