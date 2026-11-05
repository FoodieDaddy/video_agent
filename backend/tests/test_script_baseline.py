"""剧本基线回归：内存数据库与直接路由调用，不启动服务、不执行模型。"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

import app.models  # noqa: F401 注册全部外键映射，共用单一 Base。
from app.api.routes import workflows as workflow_routes
from app.api.schemas import ReviewDecision
from app.models.character import Character
from app.models.ops import WorkflowRun
from app.models.story import Script
from app.modules.platform.configuration.config_models import WorkflowNodeConfig
from app.modules.platform.exceptions import ConflictError, ValidationAppError, WorkflowError
from app.modules.platform.persistence.base import Base
from app.modules.projects.public import create_project
from app.modules.reviews.application import service as reviews
from app.modules.story import public as story
from app.modules.story.contracts import ScriptBaselineReference
from app.modules.workflow.application.engine import WorkflowEngine
from app.modules.workflow.application.handlers import HandlerContext, handle_script


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False, autoflush=False) as session:
        yield session
    engine.dispose()


@pytest.fixture()
def project(db):
    return create_project(db, owner_id="baseline-owner", name="剧本基线")


def save(db, project, *, base=None, text="林简在书店接过苏晚的信。"):
    return story.create_script_version(
        db,
        project=project,
        title="书店",
        script_text=text,
        base_script_id=base.id if base else None,
        content={"events": [{"title": "交接", "description": "接过信", "importance": 0.5}]},
    )


def parked_run(db, project, script, *, baseline="valid"):
    output = {"script_id": script.id}
    if baseline == "valid":
        output["script_fingerprint"] = story.script_fingerprint(script)
    outputs = {"analyze_script": output} if baseline != "none" else {"characters": {"count": 1}}
    run = WorkflowRun(
        project_id=project.id,
        status="awaiting_review",
        state={"next_index": 3, "outputs": outputs},
    )
    db.add(run)
    db.flush()
    return run


def change_base(db, project, script, change):
    if change == "new_version":
        save(db, project, base=script, text="另一版正文")
    elif change == "legacy_patch":
        story.update_script(db, script=script, content={**script.content, "script_text": "原位替换的正文"})


def test_fingerprint_is_stable_and_excludes_record_and_process_metadata(db, project):
    script = save(db, project)
    expected = story.script_fingerprint(script)
    script.status = "approved"
    script.approved = True
    script.version = 42
    script.model_id = "different-provenance"
    script.content = {
        **dict(reversed(list(script.content.items()))),
        "status": "approved",
        "approved": True,
        "workspace_meta": {"requires_reconfirmation": False, "source": "restore"},
    }
    assert story.script_fingerprint(script) == expected


@pytest.mark.parametrize("field", ["title", "logline", "synopsis", "genre", "tone", "body", "structure"])
def test_fingerprint_changes_for_each_business_input(db, project, field):
    script = save(db, project)
    expected = story.script_fingerprint(script)
    if field == "body":
        script.content = {**script.content, "script_text": script.content["script_text"] + "\n"}
    elif field == "structure":
        content = deepcopy(script.content)
        content["events"][0]["description"] = "新的事件内容"
        script.content = content
    else:
        setattr(script, field, "新的业务值")
    assert story.script_fingerprint(script) != expected


def test_public_assertion_refreshes_cached_orm_content(db, project):
    script = save(db, project)
    expected = story.script_fingerprint(script)
    assert story.assert_script_baseline(db, project.id, script.id, expected) is script
    # 模拟缓存之外的原位 SQL 修改；刷新查询不能拿 identity map 中旧内容放行。
    db.execute(
        update(Script)
        .where(Script.id == script.id)
        .values(content={**script.content, "script_text": "已经变化"})
        .execution_options(synchronize_session=False)
    )
    with pytest.raises(ConflictError, match="正文或结构已更新"):
        story.assert_script_baseline(db, project.id, script.id, expected)


def test_cross_module_baseline_reference_returns_dto_and_keeps_same_guard(db, project):
    script = save(db, project)
    expected = story.script_fingerprint(script)

    reference = story.assert_script_baseline_reference(db, project.id, script.id, expected)

    assert isinstance(reference, ScriptBaselineReference)
    assert (reference.project_id, reference.script_id, reference.version, reference.fingerprint) == (
        project.id,
        script.id,
        script.version,
        expected,
    )
    assert not hasattr(reference, "__table__")

    story.update_script(db, script=script, content={**script.content, "script_text": "新正文"})
    with pytest.raises(ConflictError, match="正文或结构已更新"):
        story.assert_script_baseline_reference(db, project.id, script.id, expected)


@pytest.mark.parametrize("change", ["new_version", "legacy_patch", "missing_fingerprint"])
def test_resume_rejects_stale_or_unverifiable_baseline_before_state_change(db, project, monkeypatch, change):
    script = save(db, project)
    run = parked_run(db, project, script, baseline="missing" if change == "missing_fingerprint" else "valid")
    change_base(db, project, script, change)
    engine = WorkflowEngine(SimpleNamespace())

    async def forbidden(*args, **kwargs):
        pytest.fail("失效基线不能进入后续节点")

    monkeypatch.setattr(engine, "run", forbidden)
    with pytest.raises(ConflictError, match="重新开始"):
        asyncio.run(engine.resume(db, run=run, project=project))
    assert run.status == "awaiting_review"
    assert run.task_id == ""


def test_resume_without_script_output_keeps_subworkflow_compatibility(db, project, monkeypatch):
    script = save(db, project)
    run = parked_run(db, project, script, baseline="none")
    engine = WorkflowEngine(SimpleNamespace())

    async def next_node(*args, **kwargs):
        return kwargs["run"]

    monkeypatch.setattr(engine, "run", next_node)
    assert asyncio.run(engine.resume(db, run=run, project=project)) is run
    assert run.status == "running"


def test_resume_preserves_status_error_priority(db, project):
    script = save(db, project)
    run = parked_run(db, project, script, baseline="missing")
    run.status = "completed"
    with pytest.raises(WorkflowError, match="无法恢复"):
        asyncio.run(WorkflowEngine(SimpleNamespace()).resume(db, run=run, project=project))


@pytest.mark.parametrize("reuse", [True, False])
def test_script_handler_records_fingerprint_for_manual_and_generated_script(db, project, monkeypatch, reuse):
    script = save(db, project)

    async def generated(*args, **kwargs):
        assert not reuse
        return script

    monkeypatch.setattr(story, "generate_script", generated)
    ctx = HandlerContext(
        db=db,
        runtime=SimpleNamespace(),
        project=project,
        task=None,
        workflow_run=parked_run(db, project, script) if reuse else None,
        node=WorkflowNodeConfig(id="analyze_script", handler="script"),
    )
    result = asyncio.run(handle_script(ctx))
    assert result["script_id"] == script.id
    assert result["script_fingerprint"] == story.script_fingerprint(script)
    assert result.get("reused_saved_script", False) is reuse


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("change", ["new_version", "legacy_patch", "missing_fingerprint"])
def test_approve_route_rejects_before_decision_asset_or_enqueue_writes(
    db, project, monkeypatch, resume, change
):
    script = save(db, project)
    run = parked_run(db, project, script, baseline="missing" if change == "missing_fingerprint" else "valid")
    review = reviews.create_review(db, project=project, stage="characters_scenes", workflow_run_id=run.id)
    character = Character(project_id=project.id, name="林简", status="draft", approved_version=0)
    db.add(character)
    change_base(db, project, script, change)
    db.commit()
    before_status = project.status

    async def forbidden(*args, **kwargs):
        pytest.fail("失效的旧审核不能排队恢复，也不能先提交决定")

    monkeypatch.setattr(workflow_routes, "run_task", forbidden)
    with pytest.raises(ConflictError, match="重新开始"):
        asyncio.run(
            workflow_routes.decide_review(
                review.id,
                ReviewDecision(status="approved", resume_workflow=resume),
                runtime=SimpleNamespace(),
                db=db,
                user=SimpleNamespace(id=project.owner_id),
            )
        )
    assert review.status == "pending" and review.reviewed_at is None
    assert review.comment == "" and review.reviewer_id == ""
    assert character.status == "draft" and character.approved_version == 0
    assert project.status == before_status
    assert not db.dirty and not db.new


@pytest.mark.parametrize("baseline", ["valid", "missing"])
def test_reject_of_old_workflow_remains_available(db, project, baseline):
    script = save(db, project)
    run = parked_run(db, project, script, baseline=baseline)
    review = reviews.create_review(db, project=project, stage="characters_scenes", workflow_run_id=run.id)
    save(db, project, base=script, text="已保存新稿")
    result = reviews.decide(db, project=project, review=review, status="rejected", comment="需要重做")
    assert result.status == "rejected" and result.comment == "需要重做"
    assert project.status == "script_ready"


@pytest.mark.parametrize("kind", ["manual", "subworkflow", "matching_fingerprint"])
def test_unrelated_or_matching_reviews_can_still_approve(db, project, kind):
    script = save(db, project)
    run = (
        None
        if kind == "manual"
        else parked_run(db, project, script, baseline="none" if kind == "subworkflow" else "valid")
    )
    review = reviews.create_review(
        db, project=project, stage="characters_scenes", workflow_run_id=run.id if run else ""
    )
    result = reviews.decide(db, project=project, review=review, status="approved")
    assert result.status == "approved"
    assert project.status == "characters_ready"


@pytest.mark.parametrize("requested", ["pending", "approved"])
def test_existing_review_errors_precede_missing_fingerprint(db, project, requested):
    script = save(db, project)
    run = parked_run(db, project, script, baseline="missing")
    review = reviews.create_review(db, project=project, stage="characters_scenes", workflow_run_id=run.id)
    review.status = "approved"
    error = ValidationAppError if requested == "pending" else ConflictError
    expected = "审核结论只能" if requested == "pending" else "该审核已经处理"
    with pytest.raises(error, match=expected):
        reviews.decide(db, project=project, review=review, status=requested)
