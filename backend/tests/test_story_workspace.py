"""剧本工作台的版本、导入、项目隔离及 AI 并发边界；所有模型调用都由 stub 替代。"""

from __future__ import annotations

import asyncio
import io
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401  注册同一个 ORM Base 的全部外键映射。
from app.models.character import Character, CharacterProfile
from app.models.story import Script, StoryEvent
from app.modules.platform.exceptions import AgentSchemaError, ConflictError, NotFoundError, ValidationAppError
from app.modules.platform.persistence.base import Base
from app.modules.projects.public import create_project
from app.modules.story.application import workspace
from app.modules.story.application.queries import get_project_script, list_script_versions, script_payload
from app.modules.story.application.use_cases import update_script
from app.schemas.script import ScriptOutput


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False, autoflush=False) as session:
        yield session
        session.rollback()
    engine.dispose()


@pytest.fixture
def project(db):
    return create_project(db, owner_id="workspace-owner", name="独立剧本工作台")


def save(db, project, text="原始正文\n", **kwargs):
    return workspace.create_script_version(db, project=project, title="书店", script_text=text, **kwargs)


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def event(title="开场"):
    return {"title": title, "description": "人物走进书店", "characters": ["林舟"], "location": "书店"}


def test_new_versions_preserve_history_and_do_not_revoke_downstream_approval(db, project):
    first = save(db, project, content={"events": [event()]})
    first.approved = True
    character = Character(project_id=project.id, name="林舟", status="approved", approved_version=1)
    db.add(character)
    db.flush()
    profile = CharacterProfile(project_id=project.id, character_id=character.id, version=1, approved=True)
    db.add(profile)
    db.flush()
    character.canonical_profile_id = profile.id
    before = deepcopy(first.content)

    second = save(db, project, base_script_id=first.id, logline="只改元信息")

    assert first.id != second.id
    assert (first.version, second.version) == (1, 2)
    assert first.approved is True and second.approved is False
    assert first.content == before
    assert character.status == "approved" and character.approved_version == 1 and profile.approved
    assert second.content["workspace_meta"]["requires_reconfirmation"] is True
    events = list(db.scalars(select(StoryEvent).order_by(StoryEvent.created_at)))
    assert {row.script_id for row in events} == {first.id, second.id}
    assert all(row.project_id == project.id for row in events)
    assert [row.id for row in list_script_versions(db, project.id)] == [second.id, first.id]
    assert script_payload(second)["script_text"] == "原始正文\n"
    assert script_payload(second)["workspace_meta"]["source"] == "manual"


def test_body_change_clears_stale_structure_but_history_remains(db, project):
    first = save(
        db,
        project,
        content={
            "events": [event()],
            "chapters": [{"index": 1, "title": "第一章", "summary": "旧摘要"}],
            "dialogues": [{"character_name": "林舟", "text": "旧对白"}],
        },
    )
    before = deepcopy(first.content)
    second = save(db, project, text="完全不同的新正文", base_script_id=first.id)
    assert all(second.content[key] == [] for key in ("events", "dialogues", "chapters"))
    assert second.content["workspace_meta"]["structure_status"] == "needs_analysis"
    assert first.content == before
    assert count(db, StoryEvent) == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"script_text": " \n"},
        {"script_text": "字" * 200001},
        {"title": " "},
        {"content": {"events": "错误类型"}},
        {"content": {"events": [{"title": "缺少描述"}]}},
    ],
)
def test_invalid_manual_input_writes_nothing(db, project, bad):
    arguments = {"title": "验收", "script_text": "正文", **bad}
    with pytest.raises(ValidationAppError):
        workspace.create_script_version(db, project=project, **arguments)
    assert count(db, Script) == count(db, StoryEvent) == 0
    assert project.status == "draft"


def test_optimistic_base_scope_and_legacy_patch_contract(db, project):
    first = save(db, project)
    with pytest.raises(ConflictError):
        save(db, project)
    second = save(db, project, base_script_id=first.id)
    with pytest.raises(ConflictError):
        save(db, project, base_script_id=first.id)
    other = create_project(db, owner_id="other", name="另一个项目")
    with pytest.raises(NotFoundError):
        get_project_script(db, other.id, first.id)
    with pytest.raises(NotFoundError):
        save(db, other, base_script_id=second.id)
    before = count(db, Script)
    update_script(db, script=second, title="旧接口仍原位保存")
    assert second.title == "旧接口仍原位保存" and second.status == "edited"
    assert count(db, Script) == before and second.version == 2


@pytest.mark.parametrize("suffix", ["txt", "md", "json", "docx"])
def test_supported_imports_store_body_without_novel_or_model(db, project, suffix):
    text = "# 书店\n林舟打开门。"
    if suffix == "json":
        content = json.dumps(
            {"title": "导入稿", "content": {"script_text": text, "events": [event()]}}, ensure_ascii=False
        ).encode()
    elif suffix == "docx":
        from docx import Document

        document = Document()
        document.add_paragraph(text)
        stream = io.BytesIO()
        document.save(stream)
        content = stream.getvalue()
    else:
        content = text.encode("utf-8-sig")
    result = workspace.import_script_version(
        db, project=project, filename=f"导入稿.{suffix}", content=content
    )
    assert result.content["script_text"] == text
    assert result.content["workspace_meta"]["source"] == "import"
    assert result.agent_id == "human" and result.model_id == ""


@pytest.mark.parametrize(
    "filename,content",
    [
        ("bad.pdf", b"text"),
        ("bad.json", b"{"),
        ("bad.json", b"[]"),
        ("deep.json", b"[" * 1500 + b"0" + b"]" * 1500),
        ("empty.txt", b"  \n"),
        ("bad.docx", b"broken"),
        ("large.txt", b"a" * (2 * 1024 * 1024 + 1)),
        ("bad.json", b'{"title":"x","script_text":123}'),
    ],
)
def test_bad_import_rejects_before_writing(db, project, filename, content):
    with pytest.raises(ValidationAppError):
        workspace.import_script_version(db, project=project, filename=filename, content=content)
    assert count(db, Script) == count(db, StoryEvent) == 0


def test_json_scope_and_event_ids_are_not_reused(db, project):
    other = create_project(db, owner_id="other", name="其他项目")
    foreign = save(db, other, content={"events": [event("其他项目事件")]})
    foreign_event = db.scalar(select(StoryEvent).where(StoryEvent.script_id == foreign.id))
    payload = {"project_id": other.id, "title": "不能越界", "script_text": "正文"}
    with pytest.raises(ValidationAppError):
        workspace.import_script_version(
            db, project=project, filename="x.json", content=json.dumps(payload).encode()
        )
    with pytest.raises(ValidationAppError):
        workspace.import_script_version(
            db,
            project=project,
            filename="x.json",
            content=json.dumps(
                {"title": "跨项目内容", "content": {"project_id": other.id, "script_text": "正文"}}
            ).encode(),
        )
    payload.update(
        project_id=project.id,
        events=[
            {
                "id": foreign_event.id,
                "script_id": foreign.id,
                "title": "复制业务值",
                "description": "导入描述",
                "character_names": ["林舟"],
                "location_name": "书店",
            }
        ],
    )
    imported = workspace.import_script_version(
        db, project=project, filename="x.json", content=json.dumps(payload).encode()
    )
    row = db.scalar(select(StoryEvent).where(StoryEvent.script_id == imported.id))
    assert row.project_id == project.id and row.id != foreign_event.id
    assert row.location_name == "书店" and row.character_names == ["林舟"]
    assert foreign_event.script_id == foreign.id and foreign_event.title == "其他项目事件"


def test_restore_copies_old_version_with_new_event_ids_and_requires_latest_base(db, project):
    first = save(db, project, content={"events": [event()]})
    first.approved = True
    db.flush()
    second = save(db, project, text="新稿", base_script_id=first.id)
    with pytest.raises(ConflictError):
        workspace.restore_script_version(db, project=project, script_id=first.id, base_script_id=first.id)
    restored = workspace.restore_script_version(
        db, project=project, script_id=first.id, base_script_id=second.id
    )
    assert restored.version == 3 and restored.approved is False and first.approved is True
    assert restored.content["script_text"] == first.content["script_text"]
    assert restored.content["events"] == first.content["events"]
    assert restored.content["workspace_meta"]["restored_from_script_id"] == first.id
    assert count(db, StoryEvent) == 2


def fake_result(text):
    return SimpleNamespace(
        output=ScriptOutput(title="AI稿", script_text=text, events=[]),
        model_id="stub-model",
        prompt_version="stub-prompt",
        config_version="stub-config",
    )


@pytest.mark.parametrize(
    "operation,reply,expected",
    [
        ("polish", "润色后的完整正文", "润色后的完整正文"),
        ("continue", "新增段落。\n", "  原稿\n\n\n新增段落。\n"),
    ],
)
def test_ai_preserves_base_and_appends_only_new_fragment(
    db, project, monkeypatch, operation, reply, expected
):
    first = save(db, project, text="  原稿\n")

    async def run_agent(*args, **kwargs):
        inputs = kwargs["payload"]
        assert inputs.operation == operation and inputs.script_text == "  原稿\n"
        assert inputs.current_script["id"] == first.id
        assert "script_text" not in inputs.current_script
        assert "script_text" not in inputs.current_script["content"]
        return fake_result(reply)

    monkeypatch.setattr(workspace, "run_agent", run_agent)
    new = asyncio.run(
        workspace.revise_script(
            db, SimpleNamespace(), project=project, base_script_id=first.id, operation=operation
        )
    )
    assert first.content["script_text"] == "  原稿\n"
    assert new.content["script_text"] == expected and new.version == 2
    assert new.model_id == "stub-model" and new.content["workspace_meta"]["source"] == operation


@pytest.mark.parametrize("reply", ["", "   ", "原稿", "原稿\n模型又复制完整正文"])
def test_ai_empty_or_echoed_continuation_never_writes_new_version(db, project, monkeypatch, reply):
    first = save(db, project, text="原稿")

    async def run_agent(*args, **kwargs):
        return fake_result(reply)

    monkeypatch.setattr(workspace, "run_agent", run_agent)
    with pytest.raises(AgentSchemaError):
        asyncio.run(
            workspace.revise_script(
                db, SimpleNamespace(), project=project, base_script_id=first.id, operation="continue"
            )
        )
    assert count(db, Script) == 1


@pytest.mark.parametrize("change", ["new_version", "legacy_patch"])
def test_ai_rechecks_base_after_call_before_any_new_script(db, project, monkeypatch, change):
    first = save(db, project)

    async def run_agent(*args, **kwargs):
        if change == "new_version":
            save(db, project, text="用户在等待期间保存的新稿", base_script_id=first.id)
        else:
            update_script(db, script=first, title="旧PATCH在等待期间编辑")
        return fake_result("AI润色稿")

    monkeypatch.setattr(workspace, "run_agent", run_agent)
    with pytest.raises(ConflictError) as error:
        asyncio.run(
            workspace.revise_script(
                db, SimpleNamespace(), project=project, base_script_id=first.id, operation="polish"
            )
        )
    assert error.value.details["generation_completed"] is True
    assert count(db, Script) == (2 if change == "new_version" else 1)


def test_ai_stale_base_is_rejected_before_external_call(db, project, monkeypatch):
    first = save(db, project)
    save(db, project, base_script_id=first.id)

    async def forbidden(*args, **kwargs):
        pytest.fail("过期稿不应发送模型请求")

    monkeypatch.setattr(workspace, "run_agent", forbidden)
    with pytest.raises(ConflictError):
        asyncio.run(
            workspace.revise_script(
                db, SimpleNamespace(), project=project, base_script_id=first.id, operation="polish"
            )
        )


def test_ai_continuation_checks_combined_size_before_writing(db, project, monkeypatch):
    first = save(db, project, text="原" * 199_990)

    async def run_agent(*args, **kwargs):
        return fake_result("新" * 20)

    monkeypatch.setattr(workspace, "run_agent", run_agent)
    with pytest.raises(AgentSchemaError):
        asyncio.run(
            workspace.revise_script(
                db, SimpleNamespace(), project=project, base_script_id=first.id, operation="continue"
            )
        )
    assert count(db, Script) == 1
