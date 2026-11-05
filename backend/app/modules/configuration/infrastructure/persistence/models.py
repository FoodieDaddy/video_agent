"""Configuration and prompt version ORM mappings."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.platform.persistence.base import Base, TimestampMixin, id_column


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
