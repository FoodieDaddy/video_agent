"""Story-owned SQLAlchemy mappings for documents, chapters, scripts and events."""

from __future__ import annotations

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from studio_platform.persistence.base import Base, TimestampMixin, id_column


class SourceDocument(Base, TimestampMixin):
    __tablename__ = "source_documents"

    id: Mapped[str] = id_column("doc")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255), default="")
    content_type: Mapped[str] = mapped_column(String(128), default="text/plain")
    asset_id: Mapped[str] = mapped_column(String(48), default="")
    size_bytes: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    error: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(48), default="")


class StoryChapter(Base, TimestampMixin):
    __tablename__ = "story_chapters"

    id: Mapped[str] = id_column("chapter")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    document_id: Mapped[str] = mapped_column(String(48), ForeignKey("source_documents.id"), index=True)
    index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(Text, default="")


class Script(Base, TimestampMixin):
    """一份剧本版本，正文与结构化内容保存在content。

    剧本工作区的新接口只追加版本；旧PATCH仍保留原位编辑兼容语义，不能将所有行
    视为技术上不可变。流程指纹用于识别这类原位内容变更。
    """

    __tablename__ = "scripts"

    id: Mapped[str] = id_column("script")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    title: Mapped[str] = mapped_column(String(255), default="")
    logline: Mapped[str] = mapped_column(Text, default="")
    synopsis: Mapped[str] = mapped_column(Text, default="")
    genre: Mapped[str] = mapped_column(String(64), default="")
    tone: Mapped[str] = mapped_column(String(120), default="")
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    source_document_id: Mapped[str] = mapped_column(String(48), default="")
    agent_id: Mapped[str] = mapped_column(String(64), default="script")
    model_id: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    config_version: Mapped[str] = mapped_column(String(32), default="")
    approved: Mapped[bool] = mapped_column(default=False)


class StoryEvent(Base, TimestampMixin):
    __tablename__ = "story_events"

    id: Mapped[str] = id_column("event")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    script_id: Mapped[str] = mapped_column(String(48), ForeignKey("scripts.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    chapter_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_name: Mapped[str] = mapped_column(String(255), default="")
    character_names: Mapped[list] = mapped_column(JSON, default=list)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
