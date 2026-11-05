"""资产登记：先写对象存储，再在调用方事务中登记数据库元数据。

数据库回滚不会自动删除已写入的文件；调用方负责失败补偿和资源清理。
本模块不提交事务，也不在读取入口中执行项目权限校验。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ops import AssetVersion
from app.models.project import Asset
from app.modules.platform import storage as storage_utils
from app.modules.platform.execution.runtime import AppRuntime
from app.modules.platform.ids import new_id


def build_key(project_id: str, kind: str, asset_id: str, extension: str) -> str:
    """按项目和资产类别构造存储键；不在此校验标识符或文件内容。"""
    extension = extension if extension.startswith(".") or not extension else f".{extension}"
    return f"projects/{project_id}/{kind}/{asset_id}{extension}"


def save_asset(
    db: Session,
    runtime: AppRuntime,
    *,
    project_id: str,
    kind: str,
    content: bytes,
    extension: str = ".bin",
    mime_type: str = "application/octet-stream",
    width: int | None = None,
    height: int | None = None,
    duration_seconds: float | None = None,
    model_id: str = "",
    prompt_version: str = "",
    config_version: str = "",
    meta: dict | None = None,
    created_by: str = "",
) -> Asset:
    """保存资产内容，并登记一条新的资产记录。

    Args:
        db: 调用方持有的会话，调用方负责项目权限和事务提交。
        runtime: 提供资产存储实现的运行时。
        content: 待保存的原始字节；类型与尺寸元数据由调用方提供。
        duration_seconds: 媒体时长，单位为秒；未知时可不提供。

    Returns:
        已 flush、仍绑定当前会话的 Asset；相同内容再次调用也会创建新资产。

    Notes:
        先写存储再写数据库，存储或数据库异常直接传播。后续数据库失败或回滚
        不会撤销存储写入；本函数没有跨资源事务，也不负责孤立文件回收。
    """
    if not extension.startswith("."):
        extension = f".{extension}"
    asset_id = new_id("asset")
    key = build_key(project_id, kind, asset_id, extension)
    runtime.storage.save_bytes(key, content)
    asset = Asset(
        id=asset_id,
        project_id=project_id,
        kind=kind,
        storage_key=key,
        mime_type=mime_type,
        size_bytes=len(content),
        width=width,
        height=height,
        duration_seconds=duration_seconds,
        checksum=storage_utils.checksum(content),
        model_id=model_id,
        prompt_version=prompt_version,
        config_version=config_version,
        meta=meta or {},
        created_by=created_by,
    )
    db.add(asset)
    db.flush()
    return asset


def record_asset_version(
    db: Session,
    *,
    project_id: str,
    asset_id: str,
    entity_type: str,
    entity_id: str,
    version: int,
    note: str = "",
    is_active: bool = True,
) -> AssetVersion:
    """追加资产版本账本，并按需将同一实体的旧 active 标记清除。

    调用方负责 asset/entity/project 的对应关系与版本分配。函数只 flush，
    不提交；返回当前会话中的账本对象。重复调用会追加记录，不执行去重。
    旧记录的 is_active 会更新，因此这里不承诺整行不可变或并发版本分配安全。
    """
    if is_active:
        (
            db.query(AssetVersion)
            .filter(
                AssetVersion.entity_type == entity_type,
                AssetVersion.entity_id == entity_id,
                AssetVersion.is_active.is_(True),
            )
            .update({"is_active": False}, synchronize_session=False)
        )
    row = AssetVersion(
        project_id=project_id,
        asset_id=asset_id,
        entity_type=entity_type,
        entity_id=entity_id,
        version=version,
        note=note,
        is_active=is_active,
    )
    db.add(row)
    db.flush()
    return row


def list_assets(db: Session, project_id: str, *, kind: str | None = None, limit: int = 200) -> list[Asset]:
    """按创建时间倒序查询项目资产；权限和 limit 合法性由调用方负责。"""
    statement = select(Asset).where(Asset.project_id == project_id)
    if kind:
        statement = statement.where(Asset.kind == kind)
    return list(db.scalars(statement.order_by(Asset.created_at.desc()).limit(limit)))


def asset_url(asset: Asset) -> str:
    return f"/media/{asset.storage_key}"


def read_asset(runtime: AppRuntime, asset: Asset) -> bytes:
    """读取资产内容，存储异常直接传播；本入口不单独验证访问权限。"""
    return runtime.read_media(asset.storage_key)


def local_path(runtime: AppRuntime, asset: Asset) -> Path:
    """取得运行时解析的本地媒体路径，远程存储适配限制由运行时决定。"""
    return runtime.media_path(asset.storage_key)


def asset_public(asset: Asset) -> dict:
    return {
        "id": asset.id,
        "kind": asset.kind,
        "url": asset_url(asset),
        "mime_type": asset.mime_type,
        "size_bytes": asset.size_bytes,
        "width": asset.width,
        "height": asset.height,
        "duration_seconds": asset.duration_seconds,
        "model_id": asset.model_id,
        "prompt_version": asset.prompt_version,
        "config_version": asset.config_version,
        "meta": asset.meta or {},
    }
