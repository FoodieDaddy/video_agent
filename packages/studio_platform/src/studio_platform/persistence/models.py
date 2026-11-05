"""Technical task record ORM mappings."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from studio_platform.constants import TaskStatus
from studio_platform.persistence.base import Base, TimestampMixin, id_column


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[str] = id_column("task")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    workflow_run_id: Mapped[str] = mapped_column(String(48), default="", index=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default=TaskStatus.PENDING.value, index=True)
    stage: Mapped[str] = mapped_column(String(64), default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    config_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(48), default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TaskEvent(Base, TimestampMixin):
    __tablename__ = "task_events"

    id: Mapped[str] = id_column("tevent")
    task_id: Mapped[str] = mapped_column(String(48), ForeignKey("tasks.id"), index=True)
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    level: Mapped[str] = mapped_column(String(16), default="info")
    event_type: Mapped[str] = mapped_column(String(64), default="progress")
    message: Mapped[str] = mapped_column(Text, default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
