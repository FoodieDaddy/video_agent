"""审核写入归属与工作流读取端口的边界回归。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401 注册共享 metadata。
from app.modules.characters import public as characters
from app.modules.characters.infrastructure.persistence.models import (
    Character,
    CharacterAsset,
    CharacterProfile,
)
from app.modules.platform.exceptions import ConfigurationError, ConflictError, NotFoundError
from app.modules.platform.persistence.base import Base
from app.modules.reviews.application import ports
from app.modules.reviews.application.service import decide
from app.modules.reviews.contracts import WorkflowReviewReference
from app.modules.scenes import public as scenes
from app.modules.scenes.infrastructure.persistence.models import Scene
from app.modules.workflow.application.review_queries import workflow_review_reference


def test_character_approval_keeps_individual_and_gate_asset_scope():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as db:
            character = Character(project_id="project", name="甲")
            other = Character(project_id="other", name="乙")
            db.add_all([character, other])
            db.flush()
            old = CharacterProfile(project_id="project", character_id=character.id, version=1)
            current = CharacterProfile(project_id="project", character_id=character.id, version=2)
            image = CharacterAsset(project_id="project", character_id=character.id, asset_id="image")
            db.add_all([old, current, image])
            db.flush()
            character.canonical_profile_id = current.id

            assert characters.approve_character_entity(db, "project", character) is character
            assert current.approved and character.approved_version == 2
            assert not old.approved and not image.approved

            characters.approve_current_characters(db, "project")
            assert image.approved
            assert other.status == "draft" and other.approved_version == 0
            assert not old.approved
    finally:
        engine.dispose()


def test_scene_approval_keeps_missing_profile_and_project_guard():
    db = Mock()
    scene = Scene(id="scene", project_id="project", name="书店", canonical_profile_id="")
    assert scenes.approve_scene_entity(db, "project", scene) is scene
    assert scene.status == "approved"
    db.get.assert_not_called()
    db.flush.assert_called_once()
    db.reset_mock()
    with pytest.raises(NotFoundError, match="场景不存在"):
        scenes.approve_scene_entity(db, "other", scene)
    db.flush.assert_not_called()


def test_workflow_reader_returns_only_project_and_script_baselines():
    db = Mock()
    db.get.return_value = SimpleNamespace(
        project_id="project",
        state={
            "outputs": {
                "script": {"script_id": "script", "script_fingerprint": "hash", "extra": [1]},
                "unrelated": {"count": 2},
                "legacy": {"script_id": "old"},
            }
        },
    )
    reference = workflow_review_reference(db, "run", "project")
    assert reference.project_id == "project"
    assert [(item.script_id, item.fingerprint) for item in reference.script_baselines] == [
        ("script", "hash"),
        ("old", None),
    ]
    assert not hasattr(reference, "state")
    db.flush.assert_not_called()
    db.commit.assert_not_called()


def test_workflow_reader_checks_project_before_interpreting_foreign_state():
    db = Mock()
    db.get.return_value = SimpleNamespace(project_id="other", state=42)
    reference = workflow_review_reference(db, "run", "project")
    assert reference == WorkflowReviewReference(project_id="other", script_baselines=())


def test_review_uses_injected_reader_before_writing_decision(monkeypatch):
    db = Mock()
    reader = Mock(return_value=WorkflowReviewReference(project_id="other", script_baselines=()))
    monkeypatch.setattr(ports, "_workflow_review_reader", reader)
    review = SimpleNamespace(id="review", status="pending", stage="shots", workflow_run_id="run")
    with pytest.raises(ConflictError, match="审核关联的工作流不存在或归属不匹配"):
        decide(db, project=SimpleNamespace(id="project"), review=review, status="approved")
    reader.assert_called_once_with(db, "run", "project")
    assert review.status == "pending"
    db.get.assert_not_called()
    db.flush.assert_not_called()


def test_review_reader_requires_explicit_assembly_and_accepts_app_loader(monkeypatch):
    monkeypatch.setattr(ports, "_workflow_review_reader", None)
    monkeypatch.setattr(ports, "_default_loader", None)
    with pytest.raises(ConfigurationError, match="审核工作流读取端口尚未装配"):
        ports.workflow_review_reader()

    reader = Mock()
    loader = Mock(side_effect=lambda: ports.configure_workflow_review_reader(reader))
    ports.configure_default_review_loader(loader)
    assert ports.workflow_review_reader() is reader
    assert ports.workflow_review_reader() is reader
    loader.assert_called_once_with()
