"""Workflow runs, review gates and review comments."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi import status as http_status

from app.api.deps import RuntimeDep, SessionDep, UserDep, owner_project, project_scope, run_task
from app.api.schemas import ReviewCommentCreate, ReviewDecision, WorkflowStart
from app.core.constants import WorkflowStatus
from app.core.exceptions import NotFoundError
from app.models.ops import Review, WorkflowRun
from app.services import reviews
from app.services import workflow as workflow_service

router = APIRouter(tags=["workflow"])


# --------------------------------------------------------------- workflow runs
@router.post("/projects/{project_id}/workflows/start", status_code=http_status.HTTP_202_ACCEPTED)
async def start_workflow(
    project_id: str,
    payload: WorkflowStart,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    project = owner_project(db, project_id, user)
    return await run_task(
        db,
        runtime,
        project=project,
        type="workflow",
        payload={"workflow_id": payload.workflow_id} if payload.workflow_id else {},
        user_id=user.id,
        wait=wait,
        timeout=600.0,
    )


@router.get("/projects/{project_id}/workflows")
def list_runs(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = workflow_service.list_runs(db, project.id)
    return {"items": [workflow_service.run_public(db, row) for row in rows], "count": len(rows)}


@router.get("/projects/{project_id}/workflows/{run_id}")
def get_run(project_id: str, run_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    run = workflow_service.get_run(db, project.id, run_id)
    checkpoints = workflow_service.checkpoints(db, run.id)
    return {
        "run": workflow_service.run_public(db, run),
        "checkpoints": [
            {
                "id": row.id,
                "node_id": row.node_id,
                "node_type": row.node_type,
                "status": row.status,
                "summary": row.summary,
                "error": row.error,
                "output": row.output or {},
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in checkpoints
        ],
    }


@router.post("/projects/{project_id}/workflows/{run_id}/resume")
async def resume_run(
    project_id: str,
    run_id: str,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    project = owner_project(db, project_id, user)
    run = workflow_service.get_run(db, project.id, run_id)
    return await run_task(
        db,
        runtime,
        project=project,
        type="workflow_resume",
        payload={"workflow_run_id": run.id},
        user_id=user.id,
        wait=wait,
        timeout=600.0,
    )


@router.post("/projects/{project_id}/workflows/{run_id}/cancel")
def cancel_run(project_id: str, run_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = owner_project(db, project_id, user)
    run = workflow_service.get_run(db, project.id, run_id)
    workflow_service.cancel(db, run)
    db.flush()
    return workflow_service.run_public(db, run)


# -------------------------------------------------------------------- reviews
@router.get("/projects/{project_id}/reviews")
def list_reviews(
    project_id: str,
    db: SessionDep,
    user: UserDep,
    status: str | None = Query(default=None),
) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = reviews.list_reviews(db, project.id, status=status)
    return {"items": [reviews.review_public(db, row) for row in rows], "count": len(rows)}


@router.get("/reviews/{review_id}")
def get_review(review_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    review = _load_review(db, review_id)
    project_scope(db, review.project_id, user)
    return reviews.review_public(db, review)


@router.post("/reviews/{review_id}")
async def decide_review(
    review_id: str,
    payload: ReviewDecision,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    """Approve or reject a gate and continue the parked workflow."""
    review = _load_review(db, review_id)
    project = owner_project(db, review.project_id, user)
    reviews.decide(
        db,
        project=project,
        review=review,
        status=payload.status,
        comment=payload.comment,
        decision=payload.decision,
        reviewer_id=user.id,
    )
    db.flush()

    response: dict[str, Any] = {"review": reviews.review_public(db, review)}
    run = db.get(WorkflowRun, review.workflow_run_id) if review.workflow_run_id else None
    if (
        payload.resume_workflow
        and payload.status == "approved"
        and run is not None
        and run.status == WorkflowStatus.AWAITING_REVIEW.value
    ):
        response.update(
            await run_task(
                db,
                runtime,
                project=project,
                type="workflow_resume",
                payload={"workflow_run_id": run.id},
                user_id=user.id,
                wait=wait,
                timeout=600.0,
            )
        )
    return response


@router.get("/reviews/{review_id}/comments")
def list_comments(review_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    review = _load_review(db, review_id)
    project_scope(db, review.project_id, user)
    rows = reviews.comments(db, review.id)
    return {
        "items": [
            {
                "id": row.id,
                "user_id": row.user_id,
                "body": row.body,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
        "count": len(rows),
    }


@router.post("/reviews/{review_id}/comments", status_code=http_status.HTTP_201_CREATED)
def add_comment(
    review_id: str,
    payload: ReviewCommentCreate,
    db: SessionDep,
    user: UserDep,
) -> dict[str, Any]:
    review = _load_review(db, review_id)
    owner_project(db, review.project_id, user)
    comment = reviews.add_comment(db, review, user_id=user.id, body=payload.body)
    db.flush()
    return {
        "id": comment.id,
        "review_id": comment.review_id,
        "user_id": comment.user_id,
        "body": comment.body,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
    }


def _load_review(db, review_id: str) -> Review:
    review = db.get(Review, review_id)
    if review is None:
        raise NotFoundError("审核记录不存在", details={"review_id": review_id})
    return review
