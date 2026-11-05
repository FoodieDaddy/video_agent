"""资产查询的 SQLAlchemy 适配；不提交或更改调用方事务。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Asset


def find_asset(db: Session, asset_id: str) -> Asset | None:
    """按记录 ID 读取资产；保持原 identity map 读取语义。"""
    return db.get(Asset, asset_id) if asset_id else None


def find_latest_asset(db: Session, project_id: str, kind: str) -> Asset | None:
    """按创建时间倒序读取项目指定类型的最近资产。"""
    return db.scalar(
        select(Asset)
        .where(Asset.project_id == project_id, Asset.kind == kind)
        .order_by(Asset.created_at.desc())
    )
