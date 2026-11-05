"""剧本工作区HTTP契约：版本、文件、权限、任务和下游接线，全部使用隔离mock。"""

from __future__ import annotations

import io
import json

import pytest
from sqlalchemy import func, select

from app.models.ops import AgentRun, ModelCallLog, Task, WorkflowRun
from app.models.story import SourceDocument
from app.modules.platform.persistence.session import session_scope


def create(client, headers, project_id, text="第一场 雨夜。\n林简：你终于回来了...", base=None, **extra):
    response = client.post(
        f"/api/v1/projects/{project_id}/scripts",
        headers=headers,
        json={"title": "书店手稿", "script_text": text, "base_script_id": base, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_manual_save_versions_and_stale_write_do_not_overwrite(client, headers, project):
    pid = project["id"]
    raw = "  第一场：雨夜\n苏晚：你回来了。\n\n"
    first = create(client, headers, pid, raw)
    assert first["script_text"] == raw
    second = create(client, headers, pid, raw + "林简推开书店的门。", first["id"])
    assert second["version"] == 2 and not second["approved"]
    for base in [None, first["id"]]:
        stale = client.post(
            f"/api/v1/projects/{pid}/scripts",
            headers=headers,
            json={"title": "过期稿", "script_text": "不得覆盖", "base_script_id": base},
        )
        assert stale.status_code == 409, stale.text
    assert client.get(f"/api/v1/scripts/{first['id']}", headers=headers).json()["script_text"] == raw
    assert client.get(f"/api/v1/projects/{pid}/script", headers=headers).json()["id"] == second["id"]
    versions = client.get(f"/api/v1/projects/{pid}/scripts", headers=headers).json()["items"]
    assert [row["version"] for row in versions] == [2, 1]
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(SourceDocument)) == 0
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 0


@pytest.mark.parametrize("suffix", ["txt", "md", "json", "docx"])
def test_import_creates_script_without_novel_parsing(client, headers, project, suffix):
    text = "第一场 夜 内 书店\n苏晚：这封信留给你。"
    if suffix == "json":
        content = json.dumps({"title": "导入稿", "script_text": text}, ensure_ascii=False).encode()
    elif suffix == "docx":
        from docx import Document

        document = Document()
        for line in text.splitlines():
            document.add_paragraph(line)
        buffer = io.BytesIO()
        document.save(buffer)
        content = buffer.getvalue()
    else:
        content = text.encode("utf-8-sig")
    response = client.post(
        f"/api/v1/projects/{project['id']}/scripts/import",
        headers=headers,
        files={"file": (f"剧本.{suffix}", content)},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert text in body["script_text"] and body["version"] == 1
    assert body["workspace_meta"]["source"] == "import"
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(SourceDocument)) == 0
        assert db.scalar(select(func.count()).select_from(Task)) == 0


@pytest.mark.parametrize(
    ("name", "content"),
    [("bad.json", b"{"), ("empty.txt", b" \n\t"), ("wrong.pdf", b"pdf"), ("bad.docx", b"not a zip")],
)
def test_invalid_import_is_a_business_error_with_no_version(client, headers, project, name, content):
    response = client.post(
        f"/api/v1/projects/{project['id']}/scripts/import",
        headers=headers,
        files={"file": (name, content)},
    )
    assert response.status_code == 422, response.text
    assert client.get(f"/api/v1/projects/{project['id']}/scripts", headers=headers).json()["count"] == 0


def test_import_limit_and_existing_version_baseline(client, headers, project):
    pid = project["id"]
    first = create(client, headers, pid)
    too_large = client.post(
        f"/api/v1/projects/{pid}/scripts/import",
        headers=headers,
        files={"file": ("large.txt", b"a" * (2 * 1024 * 1024 + 1))},
    )
    assert too_large.status_code == 422
    no_base = client.post(
        f"/api/v1/projects/{pid}/scripts/import", headers=headers, files={"file": ("稿.txt", b"text")}
    )
    assert no_base.status_code == 409
    imported = client.post(
        f"/api/v1/projects/{pid}/scripts/import",
        headers=headers,
        data={"base_script_id": first["id"]},
        files={"file": ("稿.txt", "第二版正文".encode())},
    )
    assert imported.status_code == 201 and imported.json()["version"] == 2


def test_restore_copies_history_and_refuses_cross_project(client, headers, project):
    pid = project["id"]
    first = create(client, headers, pid, "第一版，必须保留")
    second = create(client, headers, pid, "第二版", first["id"])
    restored = client.post(
        f"/api/v1/projects/{pid}/scripts/{first['id']}/restore",
        headers=headers,
        json={"base_script_id": second["id"]},
    )
    assert restored.status_code == 201, restored.text
    assert restored.json()["version"] == 3 and restored.json()["script_text"] == first["script_text"]
    assert restored.json()["id"] not in {first["id"], second["id"]}
    other = client.post("/api/v1/projects", headers=headers, json={"name": "另一个项目"}).json()
    foreign = create(client, headers, other["id"])
    response = client.post(
        f"/api/v1/projects/{pid}/scripts/{foreign['id']}/restore",
        headers=headers,
        json={"base_script_id": restored.json()["id"]},
    )
    assert response.status_code == 404


def test_script_assist_uses_real_task_pipeline_with_mock_provider(client, headers, project):
    pid = project["id"]
    first = create(client, headers, pid)
    current = first
    for operation in ["polish", "continue"]:
        response = client.post(
            f"/api/v1/projects/{pid}/scripts/assist?wait=true",
            headers=headers,
            json={"operation": operation, "base_script_id": current["id"], "instruction": "保留角色和情节"},
        )
        assert response.status_code == 202, response.text
        task = response.json()["task"]
        assert task["status"] == "succeeded", task
        latest = client.get(f"/api/v1/projects/{pid}/script", headers=headers).json()
        assert latest["id"] == task["result"]["script_id"]
        assert latest["workspace_meta"]["source"] == operation
        if operation == "continue":
            assert latest["script_text"].startswith(current["script_text"] + "\n\n")
            assert len(latest["script_text"]) > len(current["script_text"])
        current = latest
    assert current["version"] == 3
    stale = client.post(
        f"/api/v1/projects/{pid}/scripts/assist",
        headers=headers,
        json={"operation": "polish", "base_script_id": first["id"]},
    )
    assert stale.status_code == 409
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Task)) == 2
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 2
        assert db.scalar(select(func.count()).select_from(ModelCallLog)) == 2


def test_new_endpoints_enforce_project_membership(client, headers, project):
    first = create(client, headers, project["id"])
    outsider = {"X-User-Id": "not-a-member"}
    for suffix, body in [
        ("scripts", {"title": "不能写", "script_text": "正文", "base_script_id": first["id"]}),
        ("scripts/assist", {"operation": "polish", "base_script_id": first["id"]}),
        (f"scripts/{first['id']}/restore", {"base_script_id": first["id"]}),
    ]:
        response = client.post(f"/api/v1/projects/{project['id']}/{suffix}", headers=outsider, json=body)
        assert response.status_code == 403


def test_manual_script_reuses_saved_body_and_blocks_stale_workflow_resume(client, headers, project):
    pid = project["id"]
    first = create(client, headers, pid, "雨夜，林简站在书店门前。苏晚拿着旧信走来。")
    response = client.post(f"/api/v1/projects/{pid}/workflows/start?wait=true", headers=headers, json={})
    assert response.status_code == 202
    task = response.json()["task"]
    assert task["status"] == "succeeded", task
    run_id = task["result"]["workflow_run_id"]
    with session_scope() as db:
        run = db.get(WorkflowRun, run_id)
        assert run.status == "awaiting_review"
        assert run.state["outputs"]["analyze_script"]["script_id"] == first["id"]
        assert db.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.agent_id == "script")) == 0
    create(client, headers, pid, "后来，书店重新开门。", first["id"])
    resumed = client.post(f"/api/v1/projects/{pid}/workflows/{run_id}/resume?wait=true", headers=headers)
    assert resumed.json()["task"]["status"] == "failed"
    assert "剧本版本已更新" in resumed.json()["task"]["error"]


def test_paid_result_audit_survives_final_base_conflict(client, headers, project, monkeypatch):
    """模型已返回但基线冲突时，任务失败也必须保留这次已产生的审计。"""
    from app.modules.platform.exceptions import ConflictError
    from app.modules.story import public as story

    first = create(client, headers, project["id"])

    async def completed_then_conflicted(db, runtime, *, project, task, **kwargs):
        run = AgentRun(
            project_id=project.id, task_id=task.id, agent_id="script", status="succeeded", cost_usd=0.25
        )
        db.add(run)
        db.flush()
        db.add(
            ModelCallLog(
                project_id=project.id,
                agent_run_id=run.id,
                provider="mock",
                capability="llm",
                status="succeeded",
                cost_usd=0.25,
            )
        )
        from app.modules.projects.public import record_project_cost

        record_project_cost(db, project.id, 0.25)
        db.flush()
        raise ConflictError("剧本已更新", details={"generation_completed": True})

    monkeypatch.setattr(story, "revise_script", completed_then_conflicted)
    response = client.post(
        f"/api/v1/projects/{project['id']}/scripts/assist?wait=true",
        headers=headers,
        json={"operation": "polish", "base_script_id": first["id"]},
    )
    assert response.json()["task"]["status"] == "failed"
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 1
        assert db.scalar(select(func.count()).select_from(ModelCallLog)) == 1
    latest = client.get(f"/api/v1/projects/{project['id']}/script", headers=headers).json()
    assert latest["id"] == first["id"]


def test_docx_expanded_size_is_checked_before_parsing(client, headers, project):
    from zipfile import ZIP_DEFLATED, ZipFile

    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"x" * (16 * 1024 * 1024 + 1))
    assert len(buffer.getvalue()) < 2 * 1024 * 1024
    response = client.post(
        f"/api/v1/projects/{project['id']}/scripts/import",
        headers=headers,
        files={"file": ("large-expanded.docx", buffer.getvalue())},
    )
    assert response.status_code == 422
    assert "解压后" in response.json()["error"]["message"]


def test_editor_preserves_genre_and_tone_not_exposed_as_form_fields(client, headers, project):
    payload = {"title": "导入手稿", "script_text": "第一场，旧书店。", "genre": "悬疑", "tone": "克制"}
    imported = client.post(
        f"/api/v1/projects/{project['id']}/scripts/import",
        headers=headers,
        files={"file": ("稿.json", json.dumps(payload, ensure_ascii=False).encode())},
    )
    assert imported.status_code == 201
    saved = create(client, headers, project["id"], payload["script_text"], imported.json()["id"])
    assert saved["genre"] == "悬疑" and saved["tone"] == "克制"
