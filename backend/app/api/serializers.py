"""Response builders shared by the routers.

Serializers are intentionally explicit dicts: the console and the tests rely on
these keys, so adding a field is a deliberate act rather than an ORM side
effect.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.project import Asset, Project
from app.services import media, pipeline, quality, reviews, tasks, workflow
from app.services.assets import asset_public


def project_public(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "owner_id": project.owner_id,
        "status": project.status,
        "language": project.language,
        "genre": project.genre,
        "aspect_ratio": project.aspect_ratio,
        "budget_limit_usd": project.budget_limit_usd,
        "spent_usd": project.spent_usd,
        "settings": project.settings or {},
        "config_version": project.config_version,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


def board_public(db: Session, board) -> dict[str, Any] | None:
    if board is None:
        return None
    return {
        "id": board.id,
        "version": board.version,
        "status": board.status,
        "approved": board.approved,
        "shots": [
            pipeline.public_shot(db, shot)
            for shot in pipeline.list_shots(db, board.project_id, board=board)
        ],
        "agent_id": board.agent_id,
        "model_id": board.model_id,
        "config_version": board.config_version,
        "prompt_version": board.prompt_version,
        "created_at": board.created_at.isoformat() if board.created_at else None,
    }


def plan_public(plan) -> dict[str, Any] | None:
    if plan is None:
        return None
    return {
        "id": plan.id,
        "version": plan.version,
        "status": plan.status,
        "approved": plan.approved,
        "content": plan.content or {},
        "agent_id": plan.agent_id,
        "model_id": plan.model_id,
        "config_version": plan.config_version,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
    }


def film_public(db: Session, asset: Asset | None) -> dict[str, Any] | None:
    return asset_public(asset) if asset is not None else None


def dashboard(db: Session, project: Project) -> dict[str, Any]:
    """Everything the project home page needs in one request."""
    run = workflow.latest_run(db, project.id)
    editing = media.latest_editing(db, project.id)
    evaluation = quality.latest_evaluation(db, project.id)
    return {
        "project": project_public(project),
        "summary": pipeline.project_summary(db, project),
        "workflow": workflow.run_public(db, run) if run is not None else None,
        "pending_reviews": [
            reviews.review_public(db, review)
            for review in reviews.list_reviews(db, project.id, status="pending")
        ],
        "tasks": [tasks.task_public(task) for task in tasks.list_tasks(db, project.id, limit=10)],
        "editing": media.editing_public(db, editing) if editing is not None else None,
        "film": film_public(db, media.latest_film_asset(db, project.id)),
        "evaluation": quality.evaluation_public(db, evaluation) if evaluation is not None else None,
    }
