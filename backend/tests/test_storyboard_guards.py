"""分镜契约与生成边界：所有数据库和Provider均为隔离测试资源。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.models.character import Character, CharacterCostume, CharacterState
from app.models.production import DirectingPlan, Shot, ShotCharacter, Storyboard
from app.models.project import Asset, Project
from app.models.scene import Scene
from app.modules.platform.exceptions import AgentSchemaError, ConflictError
from app.modules.platform.persistence.session import session_scope
from app.modules.production.application import use_cases
from app.modules.projects.public import create_project
from app.modules.story import public as story
from app.schemas.storyboard import ShotDraft, StoryboardOutput


@pytest.fixture()
def prepared(client, headers, project):
    pid = project["id"]
    script = client.post(
        f"/api/v1/projects/{pid}/scripts",
        headers=headers,
        json={"title": "完整正文基线", "script_text": "第一场 旧书店 夜\n苏晚：别关灯。正文末尾独有线索。"},
    ).json()
    response = client.post(f"/api/v1/projects/{pid}/direct?wait=true", headers=headers)
    assert response.status_code == 200 and response.json()["task"]["status"] == "succeeded"
    return pid, script


def result(shots):
    return SimpleNamespace(
        output=StoryboardOutput(title="测试分镜", shots=shots),
        model_id="stub",
        prompt_version="stub-prompt",
        config_version="stub-config",
    )


@pytest.mark.parametrize("shots", [[], [{"description": ""}], [{"description": " \n "}]])
def test_empty_shot_list_or_description_is_rejected(shots):
    with pytest.raises(ValidationError):
        StoryboardOutput.model_validate({"shots": shots})


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf"), 61])
def test_invalid_duration_is_not_silently_clamped(duration):
    with pytest.raises(ValidationError):
        ShotDraft(description="有效描述", duration_seconds=duration)


@pytest.mark.parametrize("reference", ["scene", "character", "asset", "costume", "state"])
def test_references_must_belong_to_current_project(client, headers, prepared, monkeypatch, reference):
    pid, _ = prepared
    with session_scope() as db:
        other = create_project(db, owner_id="tester", name="另一个项目")
        foreign = Character(project_id=other.id, name="外部人物")
        own = Character(project_id=pid, name="当前人物")
        db.add_all([foreign, own])
        db.flush()
        scene = Scene(project_id=other.id, name="外部独有场景")
        asset = Asset(project_id=other.id, kind="image", storage_key="foreign.png", mime_type="image/png")
        costume = CharacterCostume(project_id=other.id, character_id=foreign.id)
        state = CharacterState(project_id=other.id, character_id=foreign.id)
        db.add_all([scene, asset, costume, state])
        db.flush()
        values = {"description": "合法文字，但引用来自其他项目"}
        if reference == "scene":
            values["scene_name"] = scene.name
        if reference == "asset":
            values["reference_asset_ids"] = [asset.id]
        if reference == "character":
            values["characters"] = [{"character_id": foreign.id}]
        if reference in {"costume", "state"}:
            values["characters"] = [
                {
                    "character_id": own.id,
                    reference + "_id": costume.id if reference == "costume" else state.id,
                }
            ]

    async def fake(*args, **kwargs):
        return result([ShotDraft.model_validate(values)])

    monkeypatch.setattr(use_cases, "run_agent", fake)
    with session_scope() as db:
        with pytest.raises(AgentSchemaError) as error:
            asyncio.run(
                use_cases.build_storyboard(
                    db, SimpleNamespace(), project=db.get(Project, pid), refine_prompts=False
                )
            )
        assert error.value.details["generation_completed"] is True
        assert db.scalar(select(func.count()).select_from(Storyboard)) == 0
        assert db.scalar(select(func.count()).select_from(Shot)) == 0


@pytest.mark.parametrize("change", ["script", "plan"])
def test_generation_source_change_never_saves_board(client, headers, prepared, monkeypatch, change):
    pid, _ = prepared

    async def fake(db, runtime, **kwargs):
        inputs = kwargs["payload"]
        assert "正文末尾独有线索" in inputs.script["script_text"]
        assert inputs.plan["source_script"]["id"]
        if change == "script":
            base = story.latest_script(db, pid)
            story.create_script_version(
                db,
                project=kwargs["project"],
                title="新稿",
                script_text="生成期间更新",
                base_script_id=base.id,
            )
        else:
            old = use_cases.latest_plan(db, pid)
            db.add(DirectingPlan(project_id=pid, version=old.version + 1, content=dict(old.content)))
            db.flush()
        return result([ShotDraft(description="有效镜头")])

    monkeypatch.setattr(use_cases, "run_agent", fake)
    with session_scope() as db:
        with pytest.raises(ConflictError) as error:
            asyncio.run(
                use_cases.build_storyboard(
                    db, SimpleNamespace(), project=db.get(Project, pid), refine_prompts=False
                )
            )
        assert error.value.details["generation_completed"]
        assert db.scalar(select(func.count()).select_from(Storyboard)) == 0


def test_source_change_during_refinement_cleans_candidate_rows(client, headers, prepared, monkeypatch):
    pid, _ = prepared
    with session_scope() as db:
        own = Character(project_id=pid, name="当前人物")
        db.add(own)
        db.flush()
        own_id = own.id

    async def fake(*args, **kwargs):
        return result([ShotDraft(description="有效镜头", characters=[{"character_id": own_id}])])

    async def refine(db, runtime, **kwargs):
        base = story.latest_script(db, pid)
        story.create_script_version(
            db,
            project=kwargs["project"],
            title="深化期间的新稿",
            script_text="来源已改变",
            base_script_id=base.id,
        )

    monkeypatch.setattr(use_cases, "run_agent", fake)
    monkeypatch.setattr(use_cases, "refine_prompts", refine)
    with session_scope() as db:
        with pytest.raises(ConflictError):
            asyncio.run(use_cases.build_storyboard(db, SimpleNamespace(), project=db.get(Project, pid)))
        for model in (Storyboard, Shot, ShotCharacter):
            assert db.scalar(select(func.count()).select_from(model)) == 0
