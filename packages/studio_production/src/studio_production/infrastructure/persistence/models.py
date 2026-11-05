"""Production-owned mappings for plans, storyboards, shots and media versions."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from studio_platform.constants import ShotStatus
from studio_platform.persistence.base import Base, TimestampMixin, id_column


class DirectingPlan(Base, TimestampMixin):
    __tablename__ = "directing_plans"
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_directing_plan"),)

    id: Mapped[str] = id_column("plan")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_id: Mapped[str] = mapped_column(String(64), default="director")
    model_id: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    config_version: Mapped[str] = mapped_column(String(32), default="")


class Storyboard(Base, TimestampMixin):
    __tablename__ = "storyboards"
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_storyboard"),)

    id: Mapped[str] = id_column("board")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    directing_plan_id: Mapped[str] = mapped_column(String(48), default="")
    title: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_id: Mapped[str] = mapped_column(String(64), default="storyboard")
    model_id: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    config_version: Mapped[str] = mapped_column(String(32), default="")


class Shot(Base, TimestampMixin):
    __tablename__ = "shots"

    id: Mapped[str] = id_column("shot")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    storyboard_id: Mapped[str] = mapped_column(String(48), ForeignKey("storyboards.id"), index=True)
    scene_id: Mapped[str] = mapped_column(String(48), default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default=ShotStatus.DRAFT.value)
    description: Mapped[str] = mapped_column(Text, default="")
    action: Mapped[str] = mapped_column(Text, default="")
    camera: Mapped[dict] = mapped_column(JSON, default=dict)
    characters: Mapped[list] = mapped_column(JSON, default=list)
    dialogue: Mapped[list] = mapped_column(JSON, default=list)
    duration_seconds: Mapped[float] = mapped_column(Float, default=5.0)
    visual_prompt: Mapped[str] = mapped_column(Text, default="")
    negative_prompt: Mapped[str] = mapped_column(Text, default="")
    reference_asset_ids: Mapped[list] = mapped_column(JSON, default=list)
    selected_video_id: Mapped[str] = mapped_column(String(48), default="")
    selected_audio_id: Mapped[str] = mapped_column(String(48), default="")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    config_version: Mapped[str] = mapped_column(String(32), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")


class ShotCharacter(Base, TimestampMixin):
    __tablename__ = "shot_characters"

    id: Mapped[str] = id_column("shotchar")
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    shot_id: Mapped[str] = mapped_column(String(48), ForeignKey("shots.id"), index=True)
    character_id: Mapped[str] = mapped_column(String(48), ForeignKey("characters.id"), index=True)
    costume_id: Mapped[str] = mapped_column(String(48), default="")
    state_id: Mapped[str] = mapped_column(String(48), default="")
    action: Mapped[str] = mapped_column(Text, default="")
    emotion: Mapped[str] = mapped_column(String(64), default="")


class VideoGeneration(Base, TimestampMixin):
    """One immutable video candidate version for a shot."""

    __tablename__ = "video_generations"
    __table_args__ = (UniqueConstraint("shot_id", "version", name="uq_video_version"),)

    id: Mapped[str] = id_column("video")
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    shot_id: Mapped[str] = mapped_column(String(48), ForeignKey("shots.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    provider: Mapped[str] = mapped_column(String(64), default="")
    model_id: Mapped[str] = mapped_column(String(128), default="")
    task_ref: Mapped[str] = mapped_column(String(128), default="")
    asset_id: Mapped[str] = mapped_column(String(48), default="")
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    reference_asset_ids: Mapped[list] = mapped_column(JSON, default=list)
    prompt: Mapped[str] = mapped_column(Text, default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    config_version: Mapped[str] = mapped_column(String(32), default="")
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str] = mapped_column(Text, default="")
    selected: Mapped[bool] = mapped_column(Boolean, default=False)


class AudioTrack(Base, TimestampMixin):
    __tablename__ = "audio_tracks"

    id: Mapped[str] = id_column("audio")
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    shot_id: Mapped[str] = mapped_column(String(48), default="", index=True)
    character_id: Mapped[str] = mapped_column(String(48), default="")
    kind: Mapped[str] = mapped_column(String(32), default="voice")
    asset_id: Mapped[str] = mapped_column(String(48), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    voice_id: Mapped[str] = mapped_column(String(120), default="")
    language: Mapped[str] = mapped_column(String(16), default="zh")
    version: Mapped[int] = mapped_column(Integer, default=1)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    start_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    provider: Mapped[str] = mapped_column(String(64), default="")
    model_id: Mapped[str] = mapped_column(String(128), default="")
    config_version: Mapped[str] = mapped_column(String(32), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class EditingProject(Base, TimestampMixin):
    __tablename__ = "editing_projects"
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_editing_version"),)

    id: Mapped[str] = id_column("edit")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    timeline: Mapped[dict] = mapped_column(JSON, default=dict)
    output_asset_id: Mapped[str] = mapped_column(String(48), default="")
    subtitle_asset_id: Mapped[str] = mapped_column(String(48), default="")
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    agent_id: Mapped[str] = mapped_column(String(64), default="editing")
    model_id: Mapped[str] = mapped_column(String(128), default="")
    config_version: Mapped[str] = mapped_column(String(32), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    error: Mapped[str] = mapped_column(Text, default="")


class EvaluationRun(Base, TimestampMixin):
    __tablename__ = "evaluation_runs"

    id: Mapped[str] = id_column("eval")
    project_id: Mapped[str] = mapped_column(String(48), ForeignKey("projects.id"), index=True)
    shot_id: Mapped[str] = mapped_column(String(48), default="")
    stage: Mapped[str] = mapped_column(String(32), default="final")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    recommendation: Mapped[str] = mapped_column(String(32), default="")
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    agent_id: Mapped[str] = mapped_column(String(64), default="evaluation")
    model_id: Mapped[str] = mapped_column(String(128), default="")
    config_version: Mapped[str] = mapped_column(String(32), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")


class EvaluationResult(Base, TimestampMixin):
    __tablename__ = "evaluation_results"

    id: Mapped[str] = id_column("evalres")
    project_id: Mapped[str] = mapped_column(String(48), index=True)
    evaluation_run_id: Mapped[str] = mapped_column(String(48), ForeignKey("evaluation_runs.id"), index=True)
    dimension: Mapped[str] = mapped_column(String(64), default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    issue_type: Mapped[str] = mapped_column(String(64), default="")
    severity: Mapped[str] = mapped_column(String(32), default="")
    description: Mapped[str] = mapped_column(Text, default="")
