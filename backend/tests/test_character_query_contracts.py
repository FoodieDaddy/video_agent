"""人物公开查询在选择规则、归属及 DTO 返回上的回归。"""

import asyncio
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from app.modules.characters import public as characters
from app.modules.characters.infrastructure.persistence.models import (
    Character,
    CharacterAsset,
    CharacterProfile,
    CharacterVoice,
)
from app.modules.platform.exceptions import NotFoundError
from app.modules.platform.persistence.session import session_scope
from app.modules.projects.public import create_project
from app.modules.scenes import public as scenes
from app.modules.scenes.infrastructure.persistence.models import Scene, SceneProfile


def test_portrait_keeps_approval_priority_and_voice_returns_detached_values(client, project):
    with session_scope() as db:
        character = Character(project_id=project["id"], name="林简")
        db.add(character)
        db.flush()
        db.add_all(
            [
                CharacterAsset(
                    project_id=project["id"],
                    character_id=character.id,
                    asset_id="approved-old",
                    kind="portrait",
                    version=1,
                    approved=True,
                ),
                CharacterAsset(
                    project_id=project["id"],
                    character_id=character.id,
                    asset_id="unapproved-new",
                    kind="portrait",
                    version=3,
                    approved=False,
                ),
                CharacterAsset(
                    project_id=project["id"],
                    character_id=character.id,
                    asset_id="wrong-kind",
                    kind="full_body",
                    version=5,
                    approved=True,
                ),
            ]
        )
        voice = CharacterVoice(project_id=project["id"], character_id=character.id, voice_id="calm")
        db.add(voice)
        db.flush()

        assert characters.portrait_asset_id(db, character.id) == "approved-old"
        reference = characters.voice_reference(db, character.id)
        voice.voice_id = "changed"
        assert reference.voice_id == "calm"
        with pytest.raises(FrozenInstanceError):
            reference.voice_id = "other"
        assert characters.voice_reference(db, "") is None


def test_metrics_count_only_requested_project(client, project):
    with session_scope() as db:
        other = create_project(db, owner_id="tester", name="其他项目")
        own = Character(project_id=project["id"], name="当前")
        foreign = Character(project_id=other.id, name="其他")
        db.add_all([own, foreign])
        db.flush()
        metrics = characters.character_metrics(db, project["id"])
        assert (metrics.characters, metrics.profiles, metrics.assets) == (1, 0, 0)
        reference = characters.find_character_reference(db, project["id"], own.id)
        assert reference.id == own.id and not hasattr(reference, "__table__")
        assert characters.find_character_reference(db, project["id"], foreign.id) is None
        with pytest.raises(NotFoundError, match="人物不存在"):
            asyncio.run(
                characters.generate_character_assets(
                    db,
                    SimpleNamespace(),
                    project=SimpleNamespace(id=project["id"]),
                    character_ids=[foreign.id],
                    kinds=(),
                )
            )


def test_generation_snapshots_detach_profiles_and_keep_missing_profile_defaults(client, project):
    with session_scope() as db:
        character = Character(project_id=project["id"], name="林简", aliases=["小林"])
        missing_profile = Character(project_id=project["id"], name="无档案人物")
        scene = Scene(project_id=project["id"], name="旧书店")
        db.add_all([character, missing_profile, scene])
        db.flush()
        character_profile = CharacterProfile(
            project_id=project["id"],
            character_id=character.id,
            content={"appearance": {"hair": "短发"}},
        )
        scene_profile = SceneProfile(
            project_id=project["id"],
            scene_id=scene.id,
            content={"visual_prompt": "雨夜书店", "lighting": {"color": "暖黄"}},
        )
        db.add_all([character_profile, scene_profile])
        db.flush()
        character.canonical_profile_id = character_profile.id
        scene.canonical_profile_id = scene_profile.id

        by_id = {item.id: item for item in characters.list_character_snapshots(db, project["id"])}
        character_snapshot = by_id[character.id]
        scene_snapshot = scenes.list_scene_snapshots(db, project["id"])[0]
        assert not hasattr(character_snapshot, "__table__")
        assert character_snapshot.name == "林简"
        assert scene_snapshot.generation_payload["visual_prompt"] == "雨夜书店"
        assert by_id[missing_profile.id].generation_payload["profile"] == {}

        character_snapshot.generation_payload["aliases"].append("副本别名")
        character_snapshot.generation_payload["profile"]["appearance"]["hair"] = "长发"
        scene_snapshot.generation_payload["profile"]["lighting"]["color"] = "冷蓝"
        assert character.aliases == ["小林"]
        assert character_profile.content["appearance"]["hair"] == "短发"
        assert scene_profile.content["lighting"]["color"] == "暖黄"
