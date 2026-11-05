"""Directing, storyboard, shot, video, audio, editing and evaluation routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from studio_api.api.deps import RuntimeDep, SessionDep, UserDep, owner_project, project_scope, run_task
from studio_api.api.schemas import DirectingRequest, ShotUpdate, StoryboardRequest
from studio_api.api.serializers import board_public, film_public, plan_public
from studio_platform.exceptions import NotFoundError
from studio_production import public as production_module
from studio_reviews import public as reviews

router = APIRouter(tags=["production"])


# ----------------------------------------------------------------- directing
@router.post("/projects/{project_id}/direct")
async def direct_project(
    project_id: str,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    payload: DirectingRequest | None = None,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    project = owner_project(db, project_id, user)
    # 在排队前拒绝旧基线或非法项目默认值；任务执行时仍重新核对，不能只依赖页面。
    request = production_module.validate_directing_request(
        db, project=project, **(payload.model_dump() if payload else {})
    )
    return await run_task(
        db, runtime, project=project, type="directing", payload=request, user_id=user.id, wait=wait
    )


@router.get("/projects/{project_id}/directing")
def get_directing(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = production_module.list_directing_plans(db, project.id)
    return {
        "plan": plan_public(rows[0], source=production_module.directing_source_status(db, rows[0]))
        if rows
        else None,
        "versions": [
            {
                "id": row.id,
                "version": row.version,
                "status": row.status,
                "approved": row.approved,
                "project_id": row.project_id,
                "agent_id": row.agent_id,
                "model_id": row.model_id,
                "prompt_version": row.prompt_version,
                "config_version": row.config_version,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                **production_module.directing_source_status(db, row),
            }
            for row in rows
        ],
    }


@router.get("/directing-plans/{plan_id}")
def get_directing_plan(plan_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    plan = production_module.get_directing_plan(db, plan_id)
    project_scope(db, plan.project_id, user)
    return plan_public(plan, source=production_module.directing_source_status(db, plan))


# ---------------------------------------------------------------- storyboard
@router.post("/projects/{project_id}/storyboards")
async def build_storyboard(
    project_id: str,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    payload: StoryboardRequest | None = None,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    project = owner_project(db, project_id, user)
    request = production_module.validate_storyboard_request(
        db, project=project, **(payload.model_dump() if payload else {})
    )
    return await run_task(
        db, runtime, project=project, type="storyboard", payload=request, user_id=user.id, wait=wait
    )


@router.get("/projects/{project_id}/storyboards")
def get_storyboard(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = production_module.list_storyboards(db, project.id)
    return {
        "board": board_public(db, rows[0] if rows else None),
        "versions": [
            {
                "id": row.id,
                "version": row.version,
                "status": row.status,
                "approved": row.approved,
                "directing_plan_id": row.directing_plan_id,
                "project_id": row.project_id,
                "agent_id": row.agent_id,
                "model_id": row.model_id,
                "config_version": row.config_version,
                "title": row.title,
                "notes": row.notes,
                "prompt_version": row.prompt_version,
                "shot_count": len(production_module.list_shots(db, project.id, board=row)),
                **production_module.storyboard_source_status(db, row),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


@router.get("/storyboards/{board_id}")
def get_storyboard_version(board_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    board = production_module.get_storyboard(db, board_id)
    project_scope(db, board.project_id, user)
    return board_public(db, board)


@router.post("/projects/{project_id}/storyboards/{board_id}/review")
def submit_storyboard_review(project_id: str, board_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = owner_project(db, project_id, user)
    board = production_module.get_storyboard(db, board_id)
    if board.project_id != project.id:
        raise NotFoundError("分镜版本不存在")
    review = reviews.create_review(
        db, project=project, stage="storyboard", target_type="storyboard", target_id=board.id
    )
    return reviews.review_public(db, review)


# -------------------------------------------------------------------- shots
@router.get("/projects/{project_id}/shots")
def list_shots(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = production_module.list_shots(db, project.id)
    return {"items": [production_module.public_shot(db, row) for row in rows], "count": len(rows)}


@router.get("/shots/{shot_id}")
def get_shot(shot_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    shot = _load_shot(db, shot_id)
    project_scope(db, shot.project_id, user)
    return production_module.public_shot(db, shot)


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
    production_module.update_shot(db, shot=shot, **data)
    db.flush()
    return production_module.public_shot(db, shot)


@router.post("/shots/{shot_id}/approve")
def approve_shot(shot_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    shot = _load_shot(db, shot_id)
    project = owner_project(db, shot.project_id, user)
    reviews.approve_shot(db, project, shot)
    db.flush()
    return production_module.public_shot(db, shot)


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
    rows = production_module.video_generations(db, shot.id)
    return {
        "shot_id": shot.id,
        "selected_video_id": shot.selected_video_id,
        "items": [production_module.video_public(db, row) for row in rows],
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
    generation = production_module.get_video_generation(db, video_id)
    production_module.select_video(db, project=project, shot=shot, generation=generation)
    db.flush()
    return {
        "shot": production_module.public_shot(db, shot),
        "video": production_module.video_public(db, generation),
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
    rows = production_module.audio_tracks(db, project.id)
    return {"items": [production_module.audio_public(db, row) for row in rows], "count": len(rows)}


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
    editing = production_module.latest_editing(db, project.id)
    versions = production_module.list_editing_versions(db, project.id)
    return {
        "editing": production_module.editing_public(db, editing) if editing else None,
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
        "film": film_public(db, production_module.latest_film_asset(db, project.id)),
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
    film = production_module.latest_film_asset(db, project.id)
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
    return await run_task(db, runtime, project=project, type="evaluation", user_id=user.id, wait=wait)


@router.get("/projects/{project_id}/evaluation")
def get_evaluation(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    run = production_module.latest_evaluation(db, project.id)
    return {
        "evaluation": production_module.evaluation_public(db, run) if run else None,
        "metrics": production_module.collect_metrics(db, project),
    }


def _load_shot(db, shot_id: str):
    """保留旧直接调用入口，镜头查询与错误映射由制作模块拥有。"""
    return production_module.get_shot(db, shot_id)
