"""Human-in-the-loop review services.

A review gate is explicit data, never a hidden sleep: the workflow engine stops
on a gate node and stores ``awaiting_stage`` on the run.  Approving a review
writes the approval onto the target artifacts (characters, storyboard, shots ...)
so downstream stages can rely on ``approved`` flags.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import ProjectStatus, ReviewStatus, ShotStatus
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.core.ids import new_id, utcnow
from app.models.character import Character, CharacterAsset
from app.models.ops import Review, ReviewComment
from app.models.production import EditingProject, Shot
from app.models.project import Project
from app.models.scene import Scene
from app.services import pipeline
from app.services.projects import touch_status

logger = logging.getLogger(__name__)

VALID_STAGES = {"characters_scenes", "storyboard", "shots", "final"}


def create_review(
    db: Session,
    *,
    project: Project,
    stage: str,
    target_type: str = "project",
    target_id: str = "",
    workflow_run_id: str = "",
) -> Review:
    if stage not in VALID_STAGES:
        raise ValidationAppError(f"未知审核阶段 '{stage}'")
    existing = pending_review(db, project.id, stage, workflow_run_id=workflow_run_id or None)
    if existing is not None:
        return existing
    review = Review(
        id=new_id("review"),
        project_id=project.id,
        workflow_run_id=workflow_run_id,
        stage=stage,
        target_type=target_type,
        target_id=target_id,
        status=ReviewStatus.PENDING.value,
    )
    db.add(review)
    db.flush()
    return review


def pending_review(
    db: Session, project_id: str, stage: str, *, workflow_run_id: str | None = None
) -> Review | None:
    statement = select(Review).where(
        Review.project_id == project_id,
        Review.stage == stage,
        Review.status == ReviewStatus.PENDING.value,
    )
    if workflow_run_id:
        statement = statement.where(Review.workflow_run_id == workflow_run_id)
    return db.scalars(statement.order_by(Review.created_at.desc())).first()


def approved_review(
    db: Session, project_id: str, stage: str, *, workflow_run_id: str | None = None
) -> Review | None:
    statement = select(Review).where(
        Review.project_id == project_id,
        Review.stage == stage,
        Review.status == ReviewStatus.APPROVED.value,
    )
    if workflow_run_id:
        statement = statement.where(Review.workflow_run_id == workflow_run_id)
    return db.scalars(statement.order_by(Review.reviewed_at.desc())).first()


def latest_stage_review(
    db: Session, project_id: str, stage: str, *, workflow_run_id: str | None = None
) -> Review | None:
    statement = select(Review).where(Review.project_id == project_id, Review.stage == stage)
    if workflow_run_id:
        statement = statement.where(Review.workflow_run_id == workflow_run_id)
    return db.scalars(statement.order_by(Review.created_at.desc())).first()


def list_reviews(db: Session, project_id: str, *, status: str | None = None) -> list[Review]:
    statement = select(Review).where(Review.project_id == project_id)
    if status:
        statement = statement.where(Review.status == status)
    return list(db.scalars(statement.order_by(Review.created_at.desc())))


def get_review(db: Session, project_id: str, review_id: str) -> Review:
    review = db.get(Review, review_id)
    if review is None or review.project_id != project_id:
        raise NotFoundError("审核记录不存在", details={"review_id": review_id})
    return review


def add_comment(db: Session, review: Review, *, user_id: str, body: str) -> ReviewComment:
    if not body.strip():
        raise ValidationAppError("评论内容不能为空")
    comment = ReviewComment(
        id=new_id("rcomment"),
        review_id=review.id,
        project_id=review.project_id,
        user_id=user_id,
        body=body.strip(),
    )
    db.add(comment)
    db.flush()
    return comment


def comments(db: Session, review_id: str) -> list[ReviewComment]:
    return list(
        db.scalars(
            select(ReviewComment)
            .where(ReviewComment.review_id == review_id)
            .order_by(ReviewComment.created_at)
        )
    )


def decide(
    db: Session,
    *,
    project: Project,
    review: Review,
    status: str,
    comment: str = "",
    decision: dict | None = None,
    reviewer_id: str = "",
) -> Review:
    if status not in {ReviewStatus.APPROVED.value, ReviewStatus.REJECTED.value}:
        raise ValidationAppError("审核结论只能是 approved 或 rejected")
    if review.status != ReviewStatus.PENDING.value:
        raise ConflictError("该审核已经处理", details={"review_id": review.id, "status": review.status})

    review.status = status
    review.comment = comment
    review.decision = decision or {}
    review.reviewer_id = reviewer_id
    review.reviewed_at = utcnow()
    db.flush()

    if status == ReviewStatus.APPROVED.value:
        _apply_approval(db, project=project, stage=review.stage)

    logger.info("review %s (%s) -> %s by %s", review.id, review.stage, status, reviewer_id)
    return review


def _apply_approval(db: Session, *, project: Project, stage: str) -> None:
    if stage == "characters_scenes":
        for character in pipeline.list_characters(db, project.id):
            profile = pipeline.profile_of(db, character)
            if profile is not None:
                profile.approved = True
                character.approved_version = profile.version
            character.status = "approved"
            for asset in db.scalars(
                select(CharacterAsset).where(CharacterAsset.character_id == character.id)
            ):
                asset.approved = True
        for scene in pipeline.list_scenes(db, project.id):
            profile = pipeline.scene_profile_of(db, scene)
            if profile is not None:
                profile.approved = True
                scene.approved_version = profile.version
            scene.status = "approved"
        touch_status(db, project, ProjectStatus.CHARACTERS_READY)

    elif stage == "storyboard":
        board = pipeline.latest_board(db, project.id)
        if board is not None:
            board.approved = True
            board.status = "approved"
        plan = pipeline.latest_plan(db, project.id)
        if plan is not None:
            plan.approved = True
            plan.status = "approved"
        for shot in pipeline.list_shots(db, project.id):
            shot.approved = True
            if shot.status == ShotStatus.DRAFT.value:
                shot.status = ShotStatus.PROMPT_READY.value
        touch_status(db, project, ProjectStatus.STORYBOARD_READY)

    elif stage == "shots":
        for shot in pipeline.list_shots(db, project.id):
            shot.approved = True
            if shot.selected_video_id:
                shot.status = ShotStatus.APPROVED.value
        touch_status(db, project, ProjectStatus.VIDEO_READY)

    elif stage == "final":
        editing = db.scalar(
            select(EditingProject)
            .where(EditingProject.project_id == project.id)
            .order_by(EditingProject.version.desc())
        )
        if editing is not None and editing.status == "rendered":
            editing.status = "approved"
        touch_status(db, project, ProjectStatus.EDITED)
    db.flush()


def review_public(db: Session, review: Review) -> dict:
    return {
        "id": review.id,
        "project_id": review.project_id,
        "workflow_run_id": review.workflow_run_id,
        "stage": review.stage,
        "target_type": review.target_type,
        "target_id": review.target_id,
        "status": review.status,
        "comment": review.comment,
        "decision": review.decision or {},
        "reviewer_id": review.reviewer_id,
        "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
        "created_at": review.created_at.isoformat() if review.created_at else None,
        "comments": [
            {
                "id": comment.id,
                "user_id": comment.user_id,
                "body": comment.body,
                "created_at": comment.created_at.isoformat() if comment.created_at else None,
            }
            for comment in comments(db, review.id)
        ],
    }


def approve_shot(db: Session, project: Project, shot: Shot) -> Shot:
    if shot.project_id != project.id:
        raise NotFoundError("镜头不存在", details={"shot_id": shot.id})
    shot.approved = True
    if shot.selected_video_id:
        shot.status = ShotStatus.APPROVED.value
    db.flush()
    return shot


def approve_character(db: Session, project: Project, character: Character) -> Character:
    if character.project_id != project.id:
        raise NotFoundError("人物不存在", details={"character_id": character.id})
    profile = pipeline.profile_of(db, character)
    if profile is not None:
        profile.approved = True
        character.approved_version = profile.version
    character.status = "approved"
    db.flush()
    return character


def approve_scene(db: Session, project: Project, scene: Scene) -> Scene:
    if scene.project_id != project.id:
        raise NotFoundError("场景不存在", details={"scene_id": scene.id})
    profile = pipeline.scene_profile_of(db, scene)
    if profile is not None:
        profile.approved = True
        scene.approved_version = profile.version
    scene.status = "approved"
    db.flush()
    return scene
