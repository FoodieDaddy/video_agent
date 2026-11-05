"""Human review record ORM mappings."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.platform.constants import ReviewStatus
from app.modules.platform.persistence.base import Base, TimestampMixin, id_column


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
