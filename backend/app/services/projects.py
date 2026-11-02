"""Projects and membership: the isolation boundary for every other service."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import ProjectStatus
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.core.ids import new_id
from app.models.project import Project, ProjectMember, User


def ensure_user(db: Session, user_id: str, *, role: str = "user", name: str = "") -> User:
    user = db.get(User, user_id)
    if user is not None:
        if role == "admin" and user.role != "admin":
            user.role = "admin"
        return user
    user = User(
        id=user_id,
        email=f"{user_id}@local",
        name=name or user_id,
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def create_project(
    db: Session,
    *,
    owner_id: str,
    name: str,
    description: str = "",
    language: str = "zh",
    genre: str = "",
    budget_limit_usd: float = 0.0,
    settings: dict | None = None,
) -> Project:
    ensure_user(db, owner_id)
    project = Project(
        owner_id=owner_id,
        name=name.strip() or "未命名项目",
        description=description,
        language=language,
        genre=genre,
        budget_limit_usd=budget_limit_usd,
        settings=settings or {},
    )
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=owner_id, role="owner"))
    db.flush()
    return project


def list_projects(db: Session, user_id: str, *, limit: int = 50) -> list[Project]:
    member_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
    statement = (
        select(Project)
        .where((Project.owner_id == user_id) | (Project.id.in_(member_ids)))
        .order_by(Project.created_at.desc())
        .limit(limit)
    )
    return list(db.scalars(statement))


def get_project(db: Session, project_id: str, user_id: str, *, require_role: str | None = None) -> Project:
    """Fetch a project and enforce isolation in one place."""
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"Project '{project_id}' not found", details={"project_id": project_id})
    if project.owner_id == user_id:
        return project
    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
        )
    )
    if membership is None:
        raise PermissionDeniedError("You do not have access to this project")
    if require_role and membership.role not in {require_role, "owner"}:
        raise PermissionDeniedError(f"Role '{require_role}' required for this action")
    return project


def touch_status(db: Session, project: Project, status: ProjectStatus | str) -> Project:
    project.status = str(status)
    db.flush()
    return project


def invite_member(db: Session, project: Project, user_id: str, role: str = "editor") -> ProjectMember:
    ensure_user(db, user_id)
    existing = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == user_id
        )
    )
    if existing:
        existing.role = role
        db.flush()
        return existing
    member = ProjectMember(id=new_id("member"), project_id=project.id, user_id=user_id, role=role)
    db.add(member)
    db.flush()
    return member
