"""Asset persistence: bytes go to object storage, metadata to the database."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.models.ops import AssetVersion
from app.models.project import Asset
from app.services.runtime import AppRuntime
from app.utils import storage as storage_utils


def build_key(project_id: str, kind: str, asset_id: str, extension: str) -> str:
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
    """Append an immutable ledger row whenever an asset is (re)generated."""
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
    statement = select(Asset).where(Asset.project_id == project_id)
    if kind:
        statement = statement.where(Asset.kind == kind)
    return list(db.scalars(statement.order_by(Asset.created_at.desc()).limit(limit)))


def asset_url(asset: Asset) -> str:
    return f"/media/{asset.storage_key}"


def read_asset(runtime: AppRuntime, asset: Asset) -> bytes:
    return runtime.read_media(asset.storage_key)


def local_path(runtime: AppRuntime, asset: Asset) -> Path:
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
