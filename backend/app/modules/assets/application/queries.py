"""跨模块资产读取；正常接口返回 DTO，旧 ORM 返回集中在兼容适配函数。"""

from sqlalchemy.orm import Session

from app.modules.assets.contracts import AssetReference
from app.modules.assets.infrastructure.persistence import repository
from app.modules.assets.infrastructure.persistence.models import Asset


def reference_of(asset: Asset) -> AssetReference:
    """把当前行投影为脱离 Session 的值对象。"""
    return AssetReference(
        asset_id=asset.id,
        project_id=asset.project_id,
        kind=asset.kind,
        storage_key=asset.storage_key,
        mime_type=asset.mime_type,
        size_bytes=asset.size_bytes,
        width=asset.width,
        height=asset.height,
        duration_seconds=asset.duration_seconds,
    )


def asset_reference(db: Session, asset_id: str) -> AssetReference | None:
    """读取资产引用；缺失返回 None，项目授权仍由调用方负责。"""
    row = repository.find_asset(db, asset_id)
    return reference_of(row) if row is not None else None


def latest_asset_reference(db: Session, project_id: str, kind: str) -> AssetReference | None:
    """读取指定类型最近资产的只读引用；不额外检查文件是否存在。"""
    row = repository.find_latest_asset(db, project_id, kind)
    return reference_of(row) if row is not None else None


def get_legacy_asset(db: Session, asset_id: str) -> Asset | None:
    """旧接口的 ORM 返回适配；新跨模块读取应使用 asset_reference。"""
    return repository.find_asset(db, asset_id)


def latest_legacy_asset(db: Session, project_id: str, kind: str) -> Asset | None:
    """保留旧成片返回类型；读取规则由同一仓储实现。"""
    return repository.find_latest_asset(db, project_id, kind)
