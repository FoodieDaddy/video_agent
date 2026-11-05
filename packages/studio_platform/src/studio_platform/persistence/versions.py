"""当前版本号查询的共享持久化操作，保持已有 max(version)+1 语义。"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session


def next_version(db: Session, column: Any, model: Any, project_id: str) -> int:
    """查询项目内下一版本；不提交事务，也不新增并发领取或重试语义。"""
    current = db.scalar(select(func.max(column)).where(model.project_id == project_id))
    return int(current or 0) + 1
