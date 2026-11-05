"""Assets module DTO boundary tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
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
