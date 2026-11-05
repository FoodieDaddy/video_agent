"""项目内部的持久化查询；使用调用方 Session，不提交事务。"""

from sqlalchemy.orm import Session

from .models import Project


def find_project(db: Session, project_id: str) -> Project | None:
    return db.get(Project, project_id)
