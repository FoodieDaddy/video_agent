"""Business asset and asset version ORM mappings."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.platform.persistence.base import Base, TimestampMixin, id_column


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
