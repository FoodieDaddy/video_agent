"""Assets module DTO boundary tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401 注册共享 metadata。
from app.modules.assets import public as assets
from app.modules.assets.contracts import AssetReference
from app.modules.assets.infrastructure.persistence.models import Asset
from app.modules.platform.persistence.base import Base
from app.modules.projects.public import create_project


class MemoryStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def save_bytes(self, key: str, content: bytes) -> None:
        self.objects[key] = content


def test_save_asset_reference_persists_asset_but_returns_immutable_dto():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    storage = MemoryStorage()
    runtime = SimpleNamespace(storage=storage)
    try:
        with Session(engine, expire_on_commit=False, autoflush=False) as db:
            project = create_project(db, owner_id="asset-owner", name="asset DTO")
            reference = assets.save_asset_reference(
                db,
                runtime,
                project_id=project.id,
                kind="source_document",
                content=b"text body",
                extension="txt",
                mime_type="text/plain",
            )

            assert isinstance(reference, AssetReference)
            assert reference.project_id == project.id
            assert reference.kind == "source_document"
            assert reference.mime_type == "text/plain"
            assert reference.size_bytes == 9
            assert storage.objects[reference.storage_key] == b"text body"
            row = db.get(Asset, reference.asset_id)
            assert row is not None and row.storage_key == reference.storage_key
            with pytest.raises(FrozenInstanceError):
                reference.asset_id = "changed"
    finally:
        engine.dispose()


def test_asset_queries_keep_project_kind_latest_and_detach_reference_values():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    runtime = SimpleNamespace(storage=MemoryStorage())
    try:
        with Session(engine, expire_on_commit=False, autoflush=False) as db:
            project = create_project(db, owner_id="asset-owner", name="query DTO")
            other = create_project(db, owner_id="asset-owner", name="other")
            first = assets.save_asset(
                db,
                runtime,
                project_id=project.id,
                kind="film",
                content=b"old",
                width=640,
                height=360,
                duration_seconds=2.5,
            )
            first.created_at = datetime(2026, 11, 1)
            second = assets.save_asset(
                db,
                runtime,
                project_id=project.id,
                kind="film",
                content=b"new",
                width=1280,
                height=720,
                duration_seconds=5.0,
            )
            second.created_at = first.created_at + timedelta(seconds=1)
            assets.save_asset(db, runtime, project_id=other.id, kind="film", content=b"other")
            assets.save_asset(db, runtime, project_id=project.id, kind="audio", content=b"audio")
            db.flush()

            latest = assets.latest_asset_reference(db, project.id, "film")
            assert latest is not None and latest.asset_id == second.id
            assert (latest.width, latest.height, latest.duration_seconds) == (1280, 720, 5.0)
            assert assets.asset_url(latest) == f"/media/{second.storage_key}"
            assert assets.asset_reference(db, first.id).asset_id == first.id
            assert assets.asset_reference(db, "missing") is None
            assert assets.asset_reference(db, "") is None
            assert assets.latest_asset_reference(db, project.id, "missing") is None
            assert assets.get_legacy_asset(db, first.id) is first
            assert assets.latest_legacy_asset(db, project.id, "film") is second

            second.width = 320
            db.expunge_all()
            assert latest.width == 1280
    finally:
        engine.dispose()
