"""Model execution and cost ledger ORM mappings."""

from __future__ import annotations

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from studio_platform.persistence.base import Base, TimestampMixin, id_column


class BudgetEvent(Base, TimestampMixin):
    """Cost ledger: one row per priced model/media call."""

    __tablename__ = "budget_events"

    id: Mapped[str] = id_column("budget")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    category: Mapped[str] = mapped_column(String(32), default="llm")
    amount_usd: Mapped[float] = mapped_column(Float, default=0.0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


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
