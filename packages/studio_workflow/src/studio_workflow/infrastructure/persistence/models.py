"""Workflow run and checkpoint ORM mappings."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from studio_platform.constants import WorkflowStatus
from studio_platform.persistence.base import Base, TimestampMixin, id_column


class WorkflowRun(Base, TimestampMixin):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = id_column("run")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    definition_id: Mapped[str] = mapped_column(String(64), default="novel_to_video")
    definition_version: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(32), default=WorkflowStatus.PENDING.value, index=True)
    current_node: Mapped[str] = mapped_column(String(64), default="")
    awaiting_stage: Mapped[str] = mapped_column(String(64), default="")
    pending_review_id: Mapped[str] = mapped_column(String(48), default="")
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    config_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    task_id: Mapped[str] = mapped_column(String(48), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WorkflowCheckpoint(Base, TimestampMixin):
    __tablename__ = "workflow_checkpoints"

    id: Mapped[str] = id_column("ckpt")
    run_id: Mapped[str] = mapped_column(String(48), ForeignKey("workflow_runs.id"), index=True)
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    node_id: Mapped[str] = mapped_column(String(64), default="")
    node_type: Mapped[str] = mapped_column(String(32), default="handler")
    status: Mapped[str] = mapped_column(String(32), default="completed")
    summary: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
