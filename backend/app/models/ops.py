"""Operational tables: tasks, agent runs, reviews, workflow checkpoints."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import ReviewStatus, TaskStatus, WorkflowStatus
from app.models.base import Base, TimestampMixin, id_column


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


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"

    id: Mapped[str] = id_column("arun")
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    task_id: Mapped[str] = mapped_column(String(48), default="", index=True)
    workflow_run_id: Mapped[str] = mapped_column(String(48), default="", index=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    model_provider: Mapped[str] = mapped_column(String(64), default="")
    model_id: Mapped[str] = mapped_column(String(128), default="")
    config_version: Mapped[str] = mapped_column(String(32), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class ModelCallLog(Base, TimestampMixin):
    __tablename__ = "model_call_logs"

    id: Mapped[str] = id_column("mcall")
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    agent_run_id: Mapped[str] = mapped_column(String(48), default="", index=True)
    provider: Mapped[str] = mapped_column(String(64), default="")
    capability: Mapped[str] = mapped_column(String(32), default="")
    model_id: Mapped[str] = mapped_column(String(128), default="")
    request_id: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), default="succeeded")
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    request_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")


class Review(Base, TimestampMixin):
    __tablename__ = "reviews"

    id: Mapped[str] = id_column("review")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    workflow_run_id: Mapped[str] = mapped_column(String(48), default="", index=True)
    stage: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(64), default="project")
    target_id: Mapped[str] = mapped_column(String(48), default="")
    status: Mapped[str] = mapped_column(String(32), default=ReviewStatus.PENDING.value)
    comment: Mapped[str] = mapped_column(Text, default="")
    decision: Mapped[dict] = mapped_column(JSON, default=dict)
    reviewer_id: Mapped[str] = mapped_column(String(48), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ReviewComment(Base, TimestampMixin):
    __tablename__ = "review_comments"

    id: Mapped[str] = id_column("rcomment")
    review_id: Mapped[str] = mapped_column(String(48), ForeignKey("reviews.id"), index=True)
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    user_id: Mapped[str] = mapped_column(String(48), default="")
    body: Mapped[str] = mapped_column(Text, default="")


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


class AssetVersion(Base, TimestampMixin):
    """Explicit version ledger for regenerated assets (audit + rollback)."""

    __tablename__ = "asset_versions"

    id: Mapped[str] = id_column("aversion")
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    asset_id: Mapped[str] = mapped_column(String(48), ForeignKey("assets.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), default="")
    entity_id: Mapped[str] = mapped_column(String(48), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
