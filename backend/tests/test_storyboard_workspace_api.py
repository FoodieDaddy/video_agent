"""模块4分镜HTTP闭环：手写基线、历史、编辑与第二审核快照。

复用临时SQLite/storage和mock Provider的client fixture；不监听端口、不访问
真实模型，也不进入图像、视频、配音或FFmpeg阶段。测试通过真实API排队生成，
直接数据库操作只用于构造权限成员与外部场景这类明确的边界夹具。
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models.ops import AgentRun, ModelCallLog, Task, WorkflowRun
from app.models.production import AudioTrack, EditingProject, Storyboard, VideoGeneration
from app.models.project import Asset, ProjectMember, User
from app.models.scene import Scene
from app.modules.platform.persistence.session import session_scope

INTRUDER = {"X-User-Id": "storyboard-intruder"}


def save_script(client, headers, pid, *, base=None, text=None):
    text = (
        text
        or "第一场 内景·旧书店·雨夜\n苏晚：把灯留下。\n" + "雨声与送信。" * 100 + "末尾独有道具：旧腕表。"
    )
    response = client.post(
        f"/api/v1/projects/{pid}/scripts",
        headers=headers,
        json={
            "title": "分镜手写基线",
            "script_text": text,
            "synopsis": "苏晚在旧书店等待一封旧信，雨停后决定送出。",
            "base_script_id": base,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def direct(client, headers, pid, sid):
    response = client.post(
        f"/api/v1/projects/{pid}/direct?wait=true",
        headers=headers,
        json={"base_script_id": sid, "shots_target": 3, "instruction": "保持克制的雨夜氛围"},
    )
    assert response.status_code == 200, response.text
    task = response.json()["task"]
    assert task["status"] == "succeeded", task
    response = client.get(f"/api/v1/directing-plans/{task['result']['plan_id']}", headers=headers)
    assert response.status_code == 200
    return response.json()


def build_board(client, headers, pid, sid, plan_id):
    response = client.post(
        f"/api/v1/projects/{pid}/storyboards?wait=true",
        headers=headers,
        json={"base_script_id": sid, "base_plan_id": plan_id, "refine_prompts": False},
    )
    assert response.status_code == 200, response.text
    task = response.json()["task"]
    assert task["status"] == "succeeded", task
    response = client.get(f"/api/v1/storyboards/{task['result']['storyboard_id']}", headers=headers)
    assert response.status_code == 200
    return response.json()


@pytest.fixture()
def prepared(client, headers, project):
    pid = project["id"]
    script = save_script(client, headers, pid)
    plan = direct(client, headers, pid, script["id"])
    board = build_board(client, headers, pid, script["id"], plan["id"])
    return {"pid": pid, "script": script, "plan": plan, "board": board}


def counts(pid):
    with session_scope() as db:
        return {
            model.__tablename__: int(
                db.scalar(select(func.count()).select_from(model).where(model.project_id == pid)) or 0
            )
            for model in (Task, AgentRun, ModelCallLog)
        }


def submit(client, headers, prepared, board=None):
    target = board or prepared["board"]
    response = client.post(
        f"/api/v1/projects/{prepared['pid']}/storyboards/{target['id']}/review", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def decide(client, headers, review_id, status, *, decision=None):
    return client.post(
        f"/api/v1/reviews/{review_id}",
        headers=headers,
        json={
            "status": status,
            "comment": "模块4隔离API验收",
            "decision": decision or {},
            "resume_workflow": False,
        },
    )


def test_manual_saved_text_reaches_storyboard_and_refinement_stays_disabled(client, headers, prepared):
    pid, board = prepared["pid"], prepared["board"]
    assert board["project_id"] == pid and board["version"] == 1
    assert board["source_status"] == "current"
    assert board["source_script"]["id"] == prepared["script"]["id"]
    assert board["directing_plan_id"] == prepared["plan"]["id"]
    assert board["title"] and board["model_id"] and board["prompt_version"] and board["config_version"]
    assert board["shots"] and not board["approved"]
    assert [row["order"] for row in board["shots"]] == list(range(1, len(board["shots"]) + 1))
    assert all(row["edit_fingerprint"] and row["camera"]["shot_type"] for row in board["shots"])
    with session_scope() as db:
        runs = list(db.scalars(select(AgentRun).where(AgentRun.project_id == pid)))
        assert len(runs) == 2 and {row.agent_id for row in runs} == {"director", "storyboard"}
        storyboard_run = next(row for row in runs if row.agent_id == "storyboard")
        assert storyboard_run.input["script"]["script_text"] == prepared["script"]["script_text"]
        assert "workspace_meta" not in storyboard_run.input["script"]
        task = db.scalar(select(Task).where(Task.project_id == pid, Task.type == "storyboard"))
        assert task.payload["refine_prompts"] is False
        assert task.payload["base_script_fingerprint"] and task.payload["base_plan_fingerprint"]
        for model in (Asset, VideoGeneration, AudioTrack, EditingProject, WorkflowRun):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_regeneration_preserves_old_board_shots_and_exposes_complete_history(client, headers, prepared):
    pid, old = prepared["pid"], prepared["board"]
    plan = direct(client, headers, pid, prepared["script"]["id"])
    latest = build_board(client, headers, pid, prepared["script"]["id"], plan["id"])
    assert latest["version"] == 2 and latest["directing_plan_id"] == plan["id"]
    response = client.get(f"/api/v1/projects/{pid}/storyboards", headers=headers)
    assert response.status_code == 200
    listing = response.json()
    assert listing["board"]["id"] == latest["id"]
    assert [row["version"] for row in listing["versions"]] == [2, 1]
    assert [row["source_status"] for row in listing["versions"]] == ["current", "stale"]
    assert all(row["shot_count"] and row["prompt_version"] for row in listing["versions"])
    historical = client.get(f"/api/v1/storyboards/{old['id']}", headers=headers).json()
    assert historical["shots"] == old["shots"]
    assert historical["directing_plan_id"] == old["directing_plan_id"]
    assert historical["source_status"] == "stale"
    response = client.patch(
        f"/api/v1/shots/{old['shots'][0]['id']}", headers=headers, json={"description": "不能改历史"}
    )
    assert response.status_code == 409
    assert client.get(f"/api/v1/storyboards/{old['id']}", headers=headers).json()["shots"] == old["shots"]


def test_board_and_review_routes_enforce_project_access(client, headers, prepared):
    pid, board = prepared["pid"], prepared["board"]
    review = submit(client, headers, prepared)
    routes = [
        ("GET", f"/api/v1/storyboards/{board['id']}", None),
        ("GET", f"/api/v1/projects/{pid}/storyboards", None),
        ("POST", f"/api/v1/projects/{pid}/storyboards", {"refine_prompts": False}),
        ("PATCH", f"/api/v1/shots/{board['shots'][0]['id']}", {"description": "不得越权"}),
        ("POST", f"/api/v1/projects/{pid}/storyboards/{board['id']}/review", None),
        ("GET", f"/api/v1/reviews/{review['id']}", None),
        ("POST", f"/api/v1/reviews/{review['id']}", {"status": "approved", "resume_workflow": False}),
    ]
    before = counts(pid)
    for method, url, payload in routes:
        response = client.request(method, url, headers=INTRUDER, **({"json": payload} if payload else {}))
        assert response.status_code == 403, (method, url, response.text)
    assert counts(pid) == before
    assert client.get("/api/v1/storyboards/missing", headers=headers).status_code == 404
    other = client.post("/api/v1/projects", headers=headers, json={"name": "其他项目"}).json()
    assert (
        client.post(
            f"/api/v1/projects/{other['id']}/storyboards/{board['id']}/review", headers=headers
        ).status_code
        == 404
    )


def test_read_only_member_can_read_but_cannot_edit_or_submit_review(client, headers, prepared):
    with session_scope() as db:
        db.add(User(id="storyboard-viewer", email="storyboard-viewer@local", name="只读成员"))
        db.flush()
        db.add(ProjectMember(project_id=prepared["pid"], user_id="storyboard-viewer", role="viewer"))
    viewer = {"X-User-Id": "storyboard-viewer", "X-User-Role": "user"}
    board = prepared["board"]
    assert client.get(f"/api/v1/storyboards/{board['id']}", headers=viewer).status_code == 200
    assert (
        client.patch(
            f"/api/v1/shots/{board['shots'][0]['id']}", headers=viewer, json={"description": "只读不能改"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/projects/{prepared['pid']}/storyboards/{board['id']}/review", headers=viewer
        ).status_code
        == 403
    )


def test_shot_optimistic_edit_preserves_precise_duration_and_rejects_stale_content(client, headers, prepared):
    board, shot = prepared["board"], prepared["board"]["shots"][0]
    payload = {
        "base_storyboard_id": board["id"],
        "base_shot_fingerprint": shot["edit_fingerprint"],
        "duration_seconds": 0.25,
        "description": "当前镜头精确修订",
    }
    response = client.patch(f"/api/v1/shots/{shot['id']}", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["duration_seconds"] == 0.25
    assert saved["edit_fingerprint"] != shot["edit_fingerprint"]
    assert not saved["approved"]
    stale = client.patch(
        f"/api/v1/shots/{shot['id']}", headers=headers, json={**payload, "description": "旧表单不能覆盖"}
    )
    assert stale.status_code == 409
    assert (
        client.get(f"/api/v1/shots/{shot['id']}", headers=headers).json()["description"]
        == saved["description"]
    )


def test_cross_project_scene_patch_is_rejected_before_any_mutation(client, headers, prepared):
    other = client.post("/api/v1/projects", headers=headers, json={"name": "外部场景项目"}).json()
    with session_scope() as db:
        scene = Scene(project_id=other["id"], name="外部场景")
        db.add(scene)
        db.flush()
        scene_id = scene.id
    shot = prepared["board"]["shots"][0]
    response = client.patch(
        f"/api/v1/shots/{shot['id']}",
        headers=headers,
        json={
            "scene_id": scene_id,
            "description": "不应保存",
            "base_shot_fingerprint": shot["edit_fingerprint"],
        },
    )
    assert response.status_code == 422
    current = client.get(f"/api/v1/shots/{shot['id']}", headers=headers).json()
    assert current["description"] == shot["description"] and current["scene_id"] == shot["scene_id"]
    assert current["edit_fingerprint"] == shot["edit_fingerprint"]


def test_review_freeze_edit_conflict_reject_and_resubmit_then_approve(client, headers, prepared):
    pid, board = prepared["pid"], prepared["board"]
    review = submit(client, headers, prepared)
    snapshot = review["target_snapshot"]
    assert review["target_status"] == "current" and review["status"] == "pending"
    assert snapshot == review["decision"]["storyboard_snapshot"]
    assert snapshot["storyboard_id"] == board["id"]
    assert snapshot["directing_plan_id"] == prepared["plan"]["id"]
    assert set(snapshot["shot_fingerprints"]) == {shot["id"] for shot in board["shots"]}
    # 同一实际快照重复提审复用pending，不新增审核或任务。
    assert submit(client, headers, prepared)["id"] == review["id"]
    before = counts(pid)
    shot = board["shots"][0]
    edit = client.patch(
        f"/api/v1/shots/{shot['id']}",
        headers=headers,
        json={"negative_prompt": "增加模糊与变形约束", "base_shot_fingerprint": shot["edit_fingerprint"]},
    )
    assert edit.status_code == 200
    assert decide(client, headers, review["id"], "approved").status_code == 409
    stale = client.get(f"/api/v1/reviews/{review['id']}", headers=headers).json()
    assert stale["status"] == "pending" and stale["target_status"] == "stale"
    assert stale["target_snapshot"] == snapshot
    assert (
        client.post(f"/api/v1/projects/{pid}/storyboards/{board['id']}/review", headers=headers).status_code
        == 409
    )
    rejected = decide(client, headers, review["id"], "rejected")
    assert rejected.status_code == 200 and rejected.json()["review"]["status"] == "rejected"
    fresh = submit(client, headers, prepared)
    assert fresh["id"] != review["id"] and fresh["target_status"] == "current"
    assert (
        fresh["target_snapshot"]["shot_fingerprints"][shot["id"]] != snapshot["shot_fingerprints"][shot["id"]]
    )
    approved = decide(
        client,
        headers,
        fresh["id"],
        "approved",
        decision={"note": "测试通过", "storyboard_snapshot": {"storyboard_id": "forged"}},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["review"]["target_snapshot"] == fresh["target_snapshot"]
    assert approved.json()["review"]["target_status"] == "current"
    assert "task_id" not in approved.json()
    assert counts(pid) == before
    current = client.get(f"/api/v1/storyboards/{board['id']}", headers=headers).json()
    assert current["approved"] and all(shot["approved"] for shot in current["shots"])
    assert client.get(f"/api/v1/directing-plans/{prepared['plan']['id']}", headers=headers).json()["approved"]


def test_negative_prompt_only_edit_clears_shot_and_board_approval(client, headers, prepared):
    review = submit(client, headers, prepared)
    assert decide(client, headers, review["id"], "approved").status_code == 200
    board = client.get(f"/api/v1/storyboards/{prepared['board']['id']}", headers=headers).json()
    shot = board["shots"][0]
    assert board["approved"] and shot["approved"]
    response = client.patch(
        f"/api/v1/shots/{shot['id']}",
        headers=headers,
        json={"negative_prompt": "仅修改负提示词", "base_shot_fingerprint": shot["edit_fingerprint"]},
    )
    assert response.status_code == 200 and not response.json()["approved"]
    current = client.get(f"/api/v1/storyboards/{board['id']}", headers=headers).json()
    assert not current["approved"] and current["status"] == "draft"
    assert current["shots"][0]["description"] == shot["description"]
    assert current["shots"][0]["negative_prompt"] == "仅修改负提示词"


@pytest.mark.parametrize("changed", ["board", "plan"])
def test_new_board_or_plan_invalidates_existing_pending_review(client, headers, prepared, changed):
    review = submit(client, headers, prepared)
    if changed == "board":
        build_board(client, headers, prepared["pid"], prepared["script"]["id"], prepared["plan"]["id"])
        # 即使导演版本未变，新分镜也令旧镜头只读；旧客户端省略base不能绕过。
        old_shot = prepared["board"]["shots"][0]
        historical_edit = client.patch(
            f"/api/v1/shots/{old_shot['id']}",
            headers=headers,
            json={"description": "省略基线也不能修改历史镜头"},
        )
        assert historical_edit.status_code == 409
    else:
        direct(client, headers, prepared["pid"], prepared["script"]["id"])
    before = counts(prepared["pid"])
    response = decide(client, headers, review["id"], "approved")
    assert response.status_code == 409
    stale = client.get(f"/api/v1/reviews/{review['id']}", headers=headers).json()
    assert stale["status"] == "pending" and stale["target_status"] == "stale"
    assert counts(prepared["pid"]) == before
    assert not client.get(f"/api/v1/storyboards/{prepared['board']['id']}", headers=headers).json()[
        "approved"
    ]


def test_stale_preflight_and_invalid_parameters_do_not_enqueue_work(client, headers, prepared):
    before = counts(prepared["pid"])
    invalid = client.post(
        f"/api/v1/projects/{prepared['pid']}/storyboards",
        headers=headers,
        json={"refine_prompts": "false"},
    )
    assert invalid.status_code == 422
    save_script(client, headers, prepared["pid"], base=prepared["script"]["id"], text="新的剧本正文")
    stale = client.post(
        f"/api/v1/projects/{prepared['pid']}/storyboards",
        headers=headers,
        json={
            "base_script_id": prepared["script"]["id"],
            "base_plan_id": prepared["plan"]["id"],
            "refine_prompts": False,
        },
    )
    assert stale.status_code == 409
    assert counts(prepared["pid"]) == before
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Storyboard)) == 1
