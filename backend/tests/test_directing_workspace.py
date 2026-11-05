"""导演规划闭环回归：隔离HTTP、mock模型、版本来源与生成冲突，不启动独立服务。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.models.ops import AgentRun, ModelCallLog, Task
from app.models.production import DirectingPlan, Shot, Storyboard
from app.models.project import Asset, Project
from app.modules.platform.exceptions import ConflictError
from app.modules.platform.persistence.session import session_scope
from app.modules.production.application import use_cases
from app.modules.story import public as story
from app.schemas.director import DirectingPlanOutput


def save_script(client, headers, pid, *, text="第一场 书店 夜\n苏晚：信还在吗？", base=None):
    response = client.post(
        f"/api/v1/projects/{pid}/scripts",
        headers=headers,
        json={"title": "手写导演基线", "script_text": text, "base_script_id": base},
    )
    assert response.status_code == 201, response.text
    return response.json()


def direct(client, headers, pid, payload=None):
    response = client.post(f"/api/v1/projects/{pid}/direct?wait=true", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    task = response.json()["task"]
    assert task["status"] == "succeeded", task
    return client.get(f"/api/v1/directing-plans/{task['result']['plan_id']}", headers=headers).json()


def test_empty_body_compatibility_and_manual_text_reach_director(client, headers, project):
    pid = project["id"]
    text = "  第一场 书店 夜\n" + "保留动作与对白。" * 1000 + "末尾独有道具：旧腕表。"
    script = save_script(client, headers, pid, text=text)
    plan = direct(client, headers, pid)
    assert plan["project_id"] == pid and plan["version"] == 1
    assert plan["source_status"] == "current"
    assert plan["source_script"]["id"] == script["id"]
    assert plan["source_script"] == plan["content"]["source_script"]
    assert plan["prompt_version"] and plan["model_id"] and plan["config_version"]
    with session_scope() as db:
        run = db.scalar(select(AgentRun).where(AgentRun.project_id == pid))
        assert run.agent_id == "director"
        assert run.input["script"]["script_text"] == text
        assert run.input["script"]["title"] == script["title"]
        assert "workspace_meta" not in run.input["script"]
        task = db.scalar(select(Task).where(Task.project_id == pid))
        assert task.payload["base_script_fingerprint"] == plan["source_script"]["fingerprint"]
        assert db.scalar(select(func.count()).select_from(Storyboard)) == 0
        assert db.scalar(select(func.count()).select_from(Shot)) == 0
        assert db.scalar(select(func.count()).select_from(Asset)) == 0


def test_versions_keep_history_request_and_source_status(client, headers, project):
    pid = project["id"]
    first = save_script(client, headers, pid)
    old = direct(client, headers, pid)
    second = save_script(client, headers, pid, text="第二稿正文。", base=first["id"])
    stale = client.get(f"/api/v1/directing-plans/{old['id']}", headers=headers).json()
    assert stale["source_status"] == "stale" and stale["content"] == old["content"]
    request = {"base_script_id": second["id"], "instruction": "保持克制的镜头表达。", "shots_target": 3}
    current = direct(client, headers, pid, request)
    assert current["version"] == 2 and current["source_status"] == "current"
    assert current["content"]["generation_request"] == {
        "instruction": request["instruction"],
        "shots_target": 3,
    }
    assert current["source_script"]["id"] == second["id"]
    listing = client.get(f"/api/v1/projects/{pid}/directing", headers=headers).json()
    assert [row["version"] for row in listing["versions"]] == [2, 1]
    assert [row["source_status"] for row in listing["versions"]] == ["current", "stale"]
    assert listing["plan"]["id"] == current["id"]
    assert (
        client.get(f"/api/v1/directing-plans/{old['id']}", headers=headers).json()["content"]
        == old["content"]
    )
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 2
        assert db.scalar(select(func.count()).select_from(ModelCallLog)) == 2


def test_preflight_rejects_missing_or_stale_source_without_task_or_model(client, headers, project):
    pid = project["id"]
    response = client.post(f"/api/v1/projects/{pid}/direct", headers=headers)
    assert response.status_code == 400
    first = save_script(client, headers, pid)
    save_script(client, headers, pid, base=first["id"], text="已有更新正文。")
    response = client.post(
        f"/api/v1/projects/{pid}/direct", headers=headers, json={"base_script_id": first["id"]}
    )
    assert response.status_code == 409
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Task)) == 0
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 0


def test_legacy_in_place_edit_marks_existing_plan_stale(client, headers, project):
    pid = project["id"]
    script = save_script(client, headers, pid)
    plan = direct(client, headers, pid)
    response = client.patch(
        f"/api/v1/scripts/{script['id']}",
        headers=headers,
        json={"content": {"script_text": "同一ID原位替换的剧本正文"}},
    )
    assert response.status_code == 200
    historical = client.get(f"/api/v1/directing-plans/{plan['id']}", headers=headers).json()
    assert historical["source_status"] == "stale"
    assert historical["source_script"]["id"] == script["id"]
    assert historical["content"] == plan["content"]


@pytest.mark.parametrize(
    "payload",
    [
        {"shots_target": 0},
        {"shots_target": 121},
        {"shots_target": True},
        {"instruction": "字" * 8001},
        {"base_script_id": ""},
    ],
)
def test_request_parameters_rejected_before_task(client, headers, project, payload):
    save_script(client, headers, project["id"])
    response = client.post(f"/api/v1/projects/{project['id']}/direct", headers=headers, json=payload)
    assert response.status_code == 422
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Task)) == 0


def test_history_permissions_and_legacy_unknown_source(client, headers, project):
    pid = project["id"]
    save_script(client, headers, pid)
    with session_scope() as db:
        plan = DirectingPlan(
            project_id=pid, version=1, content={"visual_style": "旧版写实方案"}, prompt_version="legacy"
        )
        db.add(plan)
        db.flush()
        plan_id = plan.id
    body = client.get(f"/api/v1/directing-plans/{plan_id}", headers=headers).json()
    assert body["source_status"] == "unknown" and body["source_script"] is None
    assert body["prompt_version"] == "legacy"
    intruder = {"X-User-Id": "intruder"}
    assert client.get(f"/api/v1/directing-plans/{plan_id}", headers=intruder).status_code == 403
    assert client.post(f"/api/v1/projects/{pid}/direct", headers=intruder).status_code == 403
    assert client.get("/api/v1/directing-plans/missing", headers=headers).status_code == 404


def test_queued_same_id_change_is_rejected_before_model(client, headers, project, monkeypatch):
    pid = project["id"]
    save_script(client, headers, pid)

    async def forbidden(*args, **kwargs):
        raise AssertionError("过期排队基线不能调用模型")

    monkeypatch.setattr(use_cases, "run_agent", forbidden)
    with session_scope() as db:
        owner = db.get(Project, pid)
        request = use_cases.validate_directing_request(db, project=owner)
        script = story.latest_script(db, pid)
        story.update_script(db, script=script, content={**script.content, "script_text": "排队期间原位改文"})
        with pytest.raises(ConflictError):
            asyncio.run(use_cases.build_directing_plan(db, SimpleNamespace(), project=owner, **request))
        assert db.scalar(select(func.count()).select_from(DirectingPlan)) == 0


@pytest.mark.parametrize("change", ["new_version", "legacy_patch"])
def test_generation_changed_source_never_writes_a_plan(client, headers, project, monkeypatch, change):
    pid = project["id"]
    first = save_script(client, headers, pid)
    observed = {}

    async def fake_agent(db, runtime, **kwargs):
        observed["payload"] = kwargs["payload"]
        script = story.latest_script(db, pid)
        if change == "new_version":
            story.create_script_version(
                db,
                project=kwargs["project"],
                title="新稿",
                script_text="生成期间的新稿",
                base_script_id=script.id,
            )
        else:
            story.update_script(
                db, script=script, content={**script.content, "script_text": "原位修改的正文"}
            )
        db.flush()
        return SimpleNamespace(
            output=DirectingPlanOutput(visual_style="有效写实风格"),
            model_id="stub",
            prompt_version="stub-prompt",
            config_version="stub-config",
        )

    monkeypatch.setattr(use_cases, "run_agent", fake_agent)
    with session_scope() as db:
        owner = db.get(Project, pid)
        with pytest.raises(ConflictError) as error:
            asyncio.run(
                use_cases.build_directing_plan(
                    db, SimpleNamespace(), project=owner, base_script_id=first["id"]
                )
            )
        assert error.value.details["generation_completed"] is True
        assert db.scalar(select(func.count()).select_from(DirectingPlan)) == 0
        assert observed["payload"].script["script_text"] == first["script_text"]


def test_completed_model_audit_survives_standalone_conflict(client, headers, project, monkeypatch):
    pid = project["id"]
    first = save_script(client, headers, pid)
    actual = use_cases.run_agent

    async def change_after_model(db, runtime, **kwargs):
        result = await actual(db, runtime, **kwargs)
        script = story.latest_script(db, pid)
        story.create_script_version(
            db,
            project=kwargs["project"],
            title="外部新稿",
            script_text="模拟在模型完成前保存的更新",
            base_script_id=script.id,
        )
        return result

    monkeypatch.setattr(use_cases, "run_agent", change_after_model)
    response = client.post(
        f"/api/v1/projects/{pid}/direct?wait=true", headers=headers, json={"base_script_id": first["id"]}
    )
    assert response.status_code == 200 and response.json()["task"]["status"] == "failed"
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(DirectingPlan)) == 0
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 1
        assert db.scalar(select(func.count()).select_from(ModelCallLog)) == 1
