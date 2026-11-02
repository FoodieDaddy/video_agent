"""Directing, storyboard, shot, video, audio, editing and evaluation routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import RuntimeDep, SessionDep, UserDep, owner_project, project_scope, run_task
from app.api.schemas import ShotUpdate
from app.api.serializers import board_public, film_public, plan_public
from app.core.exceptions import NotFoundError
from app.models.production import DirectingPlan, EditingProject, Shot, Storyboard, VideoGeneration
from app.services import media, pipeline, quality, reviews

router = APIRouter(tags=["production"])


# ----------------------------------------------------------------- directing
@router.post("/projects/{project_id}/direct")
async def direct_project(
    project_id: str,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    project = owner_project(db, project_id, user)
    return await run_task(
        db, runtime, project=project, type="directing", user_id=user.id, wait=wait
    )


@router.get("/projects/{project_id}/directing")
def get_directing(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = list(
        db.scalars(
            select(DirectingPlan)
            .where(DirectingPlan.project_id == project.id)
            .order_by(DirectingPlan.version.desc())
        )
    )
    return {
        "plan": plan_public(rows[0] if rows else None),
        "versions": [
            {
                "id": row.id,
                "version": row.version,
                "status": row.status,
                "approved": row.approved,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


# ---------------------------------------------------------------- storyboard
@router.post("/projects/{project_id}/storyboards")
async def build_storyboard(
    project_id: str,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    project = owner_project(db, project_id, user)
    return await run_task(
        db, runtime, project=project, type="storyboard", user_id=user.id, wait=wait
    )


@router.get("/projects/{project_id}/storyboards")
def get_storyboard(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = list(
        db.scalars(
            select(Storyboard)
            .where(Storyboard.project_id == project.id)
            .order_by(Storyboard.version.desc())
        )
    )
    return {
        "board": board_public(db, rows[0] if rows else None),
        "versions": [
            {
                "id": row.id,
                "version": row.version,
                "status": row.status,
                "approved": row.approved,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


# -------------------------------------------------------------------- shots
@router.get("/projects/{project_id}/shots")
def list_shots(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = pipeline.list_shots(db, project.id)
    return {"items": [pipeline.public_shot(db, row) for row in rows], "count": len(rows)}


@router.get("/shots/{shot_id}")
def get_shot(shot_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    shot = _load_shot(db, shot_id)
    project_scope(db, shot.project_id, user)
    return pipeline.public_shot(db, shot)


@router.patch("/shots/{shot_id}")
def update_shot(
    shot_id: str,
    payload: ShotUpdate,
    db: SessionDep,
    user: UserDep,
) -> dict[str, Any]:
    shot = _load_shot(db, shot_id)
    owner_project(db, shot.project_id, user)
    data = payload.model_dump(exclude_unset=True)
    pipeline.update_shot(db, shot=shot, **data)
    db.flush()
    return pipeline.public_shot(db, shot)


@router.post("/shots/{shot_id}/approve")
def approve_shot(shot_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    shot = _load_shot(db, shot_id)
    project = owner_project(db, shot.project_id, user)
    reviews.approve_shot(db, project, shot)
    db.flush()
    return pipeline.public_shot(db, shot)


@router.post("/shots/{shot_id}/generate")
async def generate_shot_video(
    shot_id: str,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    shot = _load_shot(db, shot_id)
    project = owner_project(db, shot.project_id, user)
    return await run_task(
        db,
        runtime,
        project=project,
        type="shot_video",
        payload={"shot_id": shot.id},
        user_id=user.id,
        wait=wait,
    )


@router.post("/projects/{project_id}/shots/generate")
async def generate_all_shot_videos(
    project_id: str,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    project = owner_project(db, project_id, user)
    return await run_task(db, runtime, project=project, type="video", user_id=user.id, wait=wait)


@router.get("/shots/{shot_id}/versions")
def shot_versions(shot_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    shot = _load_shot(db, shot_id)
    project_scope(db, shot.project_id, user)
    rows = media.video_generations(db, shot.id)
    return {
        "shot_id": shot.id,
        "selected_video_id": shot.selected_video_id,
        "items": [media.video_public(db, row) for row in rows],
        "count": len(rows),
    }


@router.post("/shots/{shot_id}/versions/{video_id}/select")
def select_shot_version(
    shot_id: str,
    video_id: str,
    db: SessionDep,
    user: UserDep,
) -> dict[str, Any]:
    shot = _load_shot(db, shot_id)
    project = owner_project(db, shot.project_id, user)
    generation = db.get(VideoGeneration, video_id)
    if generation is None:
        raise NotFoundError("视频版本不存在", details={"video_id": video_id})
    media.select_video(db, project=project, shot=shot, generation=generation)
    db.flush()
    return {
        "shot": pipeline.public_shot(db, shot),
        "video": media.video_public(db, generation),
    }


# -------------------------------------------------------------------- audio
@router.post("/projects/{project_id}/audio")
async def generate_audio(
    project_id: str,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    project = owner_project(db, project_id, user)
    return await run_task(db, runtime, project=project, type="audio", user_id=user.id, wait=wait)


@router.get("/projects/{project_id}/audio")
def list_audio(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = media.audio_tracks(db, project.id)
    return {"items": [media.audio_public(db, row) for row in rows], "count": len(rows)}


# ------------------------------------------------------------------ editing
@router.post("/projects/{project_id}/editing")
async def build_editing(
    project_id: str,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    project = owner_project(db, project_id, user)
    return await run_task(db, runtime, project=project, type="editing", user_id=user.id, wait=wait)


@router.get("/projects/{project_id}/editing")
def get_editing(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    editing = media.latest_editing(db, project.id)
    versions = list(
        db.scalars(
            select(EditingProject)
            .where(EditingProject.project_id == project.id)
            .order_by(EditingProject.version.desc())
        )
    )
    return {
        "editing": media.editing_public(db, editing) if editing else None,
        "versions": [
            {
                "id": row.id,
                "version": row.version,
                "status": row.status,
                "duration_seconds": row.duration_seconds,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in versions
        ],
        "film": film_public(db, media.latest_film_asset(db, project.id)),
    }


@router.post("/projects/{project_id}/render")
async def render_project(
    project_id: str,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    wait: bool = Query(default=True),
) -> dict[str, Any]:
    project = owner_project(db, project_id, user)
    return await run_task(db, runtime, project=project, type="render", user_id=user.id, wait=wait)


@router.post("/projects/{project_id}/export")
async def export_project(
    project_id: str,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    project = owner_project(db, project_id, user)
    return await run_task(db, runtime, project=project, type="export", user_id=user.id, wait=wait)


@router.get("/projects/{project_id}/export")
def get_export(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    film = media.latest_film_asset(db, project.id)
    return {"film": film_public(db, film), "ready": film is not None}


# --------------------------------------------------------------- evaluation
@router.post("/projects/{project_id}/evaluate")
async def evaluate(
    project_id: str,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    project = owner_project(db, project_id, user)
    # The evaluation stage is fixed at "final" for the report card; keeping the
    # task payload empty lets the stage router resolve the handler by task type.
    return await run_task(
        db, runtime, project=project, type="evaluation", user_id=user.id, wait=wait
    )


@router.get("/projects/{project_id}/evaluation")
def get_evaluation(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    run = quality.latest_evaluation(db, project.id)
    return {
        "evaluation": quality.evaluation_public(db, run) if run else None,
        "metrics": quality.collect_metrics(db, project),
    }


def _load_shot(db, shot_id: str) -> Shot:
    shot = db.get(Shot, shot_id)
    if shot is None:
        raise NotFoundError("镜头不存在", details={"shot_id": shot_id})
    return shot
