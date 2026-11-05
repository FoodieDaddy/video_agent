"""项目、成员与访问权限用例。

除 get_project 显式检查项目访问外，写用例要求调用方已验证操作权限和输入角色。
本文件只使用传入 Session 并 flush；提交、回滚和并发控制由调用方负责。
返回 ORM 实体仍属于兼容契约，不能将其当成脱离 Session 的不可变 DTO。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project, ProjectMember, User
from app.modules.platform.constants import ProjectStatus
from app.modules.platform.exceptions import NotFoundError, PermissionDeniedError
from app.modules.platform.ids import new_id


def ensure_user(db: Session, user_id: str, *, role: str = "user", name: str = "") -> User:
    """按 user_id 读取或创建用户，并返回同一 Session 中的 User。

    已有用户仅在请求 role="admin" 时升级角色；不降级角色，不更新已有姓名。
    写入只 flush，不提交；同 ID 顺序重试通常复用记录，并发创建仍由调用方协调。
    """
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
    """创建项目、所有者用户及 owner 成员关系。

    Args:
        db: 调用方事务 Session，只 flush，不提交。
        owner_id: 已完成身份验证的所有者 ID。
        name: 去首尾空白后的项目名；空名使用默认标题。

    Returns:
        已分配 ID、仍属于当前 Session 的 Project。

    Notes:
        会写用户、项目和成员记录，无外部模型调用；重复请求创建新项目。
        失败由外层回滚，本函数不提供幂等键或并发创建保护。
    """
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
    """读取用户拥有或作为成员加入的项目，最多返回 limit 条。

    此查询不写入或提交；返回 ORM 列表，未匹配时为空。当前排序使用创建时间降序。
    """
    member_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
    statement = (
        select(Project)
        .where((Project.owner_id == user_id) | (Project.id.in_(member_ids)))
        .order_by(Project.created_at.desc())
        .limit(limit)
    )
    return list(db.scalars(statement))


def get_project(db: Session, project_id: str, user_id: str, *, require_role: str | None = None) -> Project:
    """读取项目并验证用户访问资格及可选成员角色。

    Args:
        project_id: 项目 ID。
        user_id: 待验证用户 ID；项目所有者直接通过。
        require_role: 成员需具有该角色或 owner，None 时只要求成员身份。

    Returns:
        当前 Session 中的 Project；不写入或提交。

    Raises:
        NotFoundError: 项目不存在。
        PermissionDeniedError: 无成员资格或角色不符。
    """
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"Project '{project_id}' not found", details={"project_id": project_id})
    if project.owner_id == user_id:
        return project
    membership = db.scalar(
        select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
    )
    if membership is None:
        raise PermissionDeniedError("You do not have access to this project")
    if require_role and membership.role not in {require_role, "owner"}:
        raise PermissionDeniedError(f"Role '{require_role}' required for this action")
    return project


def touch_status(db: Session, project: Project, status: ProjectStatus | str) -> Project:
    """将项目状态设置为给定值并 flush，返回原 Project。

    本操作不校验状态迁移是否合法；业务前置条件与事务提交均由调用方负责。
    """
    project.status = str(status)
    db.flush()
    return project


def invite_member(db: Session, project: Project, user_id: str, role: str = "editor") -> ProjectMember:
    """确保用户存在，并创建或更新该项目成员角色。

    前置：调用方已验证邀请权限、目标用户和角色；本函数不重复执行这些校验。
    同一项目与用户的顺序调用会复用成员行并覆盖角色；仅 flush，不提交。
    """
    ensure_user(db, user_id)
    existing = db.scalar(
        select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user_id)
    )
    if existing:
        existing.role = role
        db.flush()
        return existing
    member = ProjectMember(id=new_id("member"), project_id=project.id, user_id=user_id, role=role)
    db.add(member)
    db.flush()
    return member
