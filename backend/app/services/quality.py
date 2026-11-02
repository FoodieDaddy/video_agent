"""Quality evaluation stage.

Metrics are collected from the database (never from the LLM), then handed to the
Evaluation agent.  The agent explains and scores; the numbers stay grounded.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import AssetKind
from app.core.ids import new_id
from app.models.character import CharacterAsset, CharacterProfile
from app.models.ops import Task
from app.models.production import (
    AudioTrack,
    EvaluationResult,
    EvaluationRun,
    VideoGeneration,
)
from app.models.project import Asset, Project
from app.schemas.evaluation import EvaluationInput
from app.services import media, pipeline
from app.services.agent_runner import run_agent
from app.services.runtime import AppRuntime

logger = logging.getLogger(__name__)


def collect_metrics(db: Session, project: Project, *, stage: str = "final") -> dict[str, Any]:
    shots = pipeline.list_shots(db, project.id)
    shot_ids = [shot.id for shot in shots]
    videos = 0
    if shot_ids:
        videos = int(
            db.scalar(
                select(func.count(VideoGeneration.id)).where(
                    VideoGeneration.shot_id.in_(shot_ids), VideoGeneration.asset_id != ""
                )
            )
            or 0
        )
    shots_with_video = sum(1 for shot in shots if shot.selected_video_id)
    audio_tracks = int(
        db.scalar(select(func.count(AudioTrack.id)).where(AudioTrack.project_id == project.id)) or 0
    )
    subtitle = db.scalar(
        select(Asset)
        .where(Asset.project_id == project.id, Asset.kind == AssetKind.SUBTITLE.value)
        .order_by(Asset.created_at.desc())
    )
    film = media.latest_film_asset(db, project.id)
    characters = pipeline.list_characters(db, project.id)
    profiles = int(
        db.scalar(
            select(func.count(CharacterProfile.id)).where(CharacterProfile.project_id == project.id)
        )
        or 0
    )
    character_images = int(
        db.scalar(
            select(func.count(CharacterAsset.id)).where(CharacterAsset.project_id == project.id)
        )
        or 0
    )
    approved_shots = sum(1 for shot in shots if shot.approved)
    editing = media.latest_editing(db, project.id)

    dialogue_lines = sum(len(shot.dialogue or []) for shot in shots)
    coverage = round(shots_with_video / len(shots), 3) if shots else 0.0
    character_consistency = 0.85 if character_images and profiles else 0.55
    if characters and character_images >= len(characters):
        character_consistency = 0.9

    return {
        "stage": stage,
        "shots": len(shots),
        "shots_with_video": shots_with_video,
        "video_candidates": videos,
        "video_coverage": coverage,
        "approved_shots": approved_shots,
        "audio_tracks": audio_tracks,
        "dialogue_lines": dialogue_lines,
        "subtitles": bool(subtitle),
        "character_count": len(characters),
        "character_profiles": profiles,
        "character_assets": character_images,
        "character_consistency": character_consistency,
        "total_duration_seconds": round(
            sum(float(shot.duration_seconds or 0) for shot in shots), 2
        ),
        "render_status": (editing.status if editing else ""),
        "rendered": bool(film),
        "final_video": bool(film),
        "budget_usd": round(float(project.spent_usd or 0.0), 4),
    }


async def evaluate_project(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    stage: str = "final",
    metrics: dict[str, Any] | None = None,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
) -> EvaluationRun:
    metrics = metrics or collect_metrics(db, project, stage=stage)
    summary = pipeline.project_summary(db, project)
    result = await run_agent(
        db,
        runtime,
        project=project,
        agent_id="evaluation",
        payload=EvaluationInput(
            stage=stage,
            metrics=metrics,
            project_summary=summary,
            thresholds=runtime.config_store.agent("evaluation").evaluation.thresholds,
        ),
        task=task,
        workflow_run_id=workflow_run_id,
        user_id=user_id,
    )
    report = result.output
    run = EvaluationRun(
        id=new_id("eval"),
        project_id=project.id,
        stage=stage,
        status="completed",
        overall_score=float(report.overall_score),
        recommendation=report.recommendation,
        report={"metrics": metrics, "summary": report.summary, "scores": report.scores},
        agent_id="evaluation",
        model_id=result.model_id,
        config_version=result.config_version,
        prompt_version=result.prompt_version,
    )
    db.add(run)
    db.flush()

    for dimension, score in report.scores.items():
        db.add(
            EvaluationResult(
                id=new_id("evalres"),
                project_id=project.id,
                evaluation_run_id=run.id,
                dimension=dimension,
                score=float(score or 0.0),
            )
        )
    for issue in report.issues:
        db.add(
            EvaluationResult(
                id=new_id("evalres"),
                project_id=project.id,
                evaluation_run_id=run.id,
                dimension=issue.type,
                score=0.0,
                issue_type=issue.type,
                severity=issue.severity,
                description=issue.description,
            )
        )
    db.flush()
    logger.info(
        "evaluation for project %s: %.2f (%s)", project.id, run.overall_score, run.recommendation
    )
    return run


def latest_evaluation(db: Session, project_id: str) -> EvaluationRun | None:
    return db.scalar(
        select(EvaluationRun)
        .where(EvaluationRun.project_id == project_id)
        .order_by(EvaluationRun.created_at.desc())
    )


def evaluation_public(db: Session, run: EvaluationRun) -> dict:
    results = list(
        db.scalars(
            select(EvaluationResult).where(EvaluationResult.evaluation_run_id == run.id)
        )
    )
    return {
        "id": run.id,
        "stage": run.stage,
        "status": run.status,
        "overall_score": run.overall_score,
        "recommendation": run.recommendation,
        "summary": (run.report or {}).get("summary", ""),
        "report": run.report or {},
        "scores": {
            row.dimension: row.score for row in results if row.dimension and not row.issue_type
        },
        "issues": [
            {
                "type": row.issue_type or row.dimension,
                "severity": row.severity,
                "description": row.description,
            }
            for row in results
            if row.issue_type
        ],
        "model_id": run.model_id,
        "config_version": run.config_version,
        "prompt_version": run.prompt_version,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }
