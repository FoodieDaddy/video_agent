"""项目上下文投影与状态/费用写入边界。"""

from copy import deepcopy

from sqlalchemy.orm import Session

from app.modules.platform.exceptions import NotFoundError
from app.modules.projects.contracts import ProjectContext
from app.modules.projects.infrastructure.persistence.repository import find_project


def find_project_context(db: Session, project_id: str) -> ProjectContext | None:
    """按 ID 读取已授权项目快照；项目权限由外层入口检查。"""
    project = find_project(db, project_id)
    if project is None:
        return None
    return ProjectContext(
        id=project.id,
        name=project.name,
        owner_id=project.owner_id,
        status=project.status,
        language=project.language,
        genre=project.genre,
        aspect_ratio=project.aspect_ratio,
        budget_limit_usd=project.budget_limit_usd,
        spent_usd=project.spent_usd,
        settings=deepcopy(project.settings or {}),
        config_version=project.config_version,
    )


def record_project_cost(db: Session, project_id: str, amount_usd: float) -> None:
    """累加既有费用字段并 flush；不新增费用事件，不另开会话或提交。"""
    project = find_project(db, project_id)
    if project is None:
        raise NotFoundError("项目不存在", details={"project_id": project_id})
    project.spent_usd = round((project.spent_usd or 0.0) + amount_usd, 6)
    db.flush()


def set_project_status(db: Session, project_id: str, status: str) -> None:
    """在所属模块写状态；保持现有任意状态赋值语义，调用方负责阶段规则。"""
    project = find_project(db, project_id)
    if project is None:
        raise NotFoundError("项目不存在", details={"project_id": project_id})
    project.status = str(status)
    db.flush()
