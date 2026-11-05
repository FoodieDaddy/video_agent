"""项目和剧本适配层迁移后的字段、错误顺序与持久化投影契约。"""

from __future__ import annotations


def test_project_write_usecases_keep_aspect_ratio_null_and_shallow_settings_merge(client, headers):
    created = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": "  项目原名  ",
            "aspect_ratio": "9:16",
            "budget_limit_usd": 8,
            "settings": {"aspect_ratio": "ignored", "keep": True, "nested": {"old": 1}},
        },
    )
    assert created.status_code == 201
    project = created.json()
    assert project["name"] == "项目原名"
    assert project["aspect_ratio"] == "9:16"
    assert project["settings"]["aspect_ratio"] == "9:16"

    updated = client.patch(
        f"/api/v1/projects/{project['id']}",
        headers=headers,
        json={
            "name": "  不裁剪 PATCH 名称  ",
            "description": "",
            "aspect_ratio": "4:3",
            "budget_limit_usd": 0,
            "settings": {"nested": {"new": 2}},
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["name"] == "  不裁剪 PATCH 名称  "
    assert body["aspect_ratio"] == "4:3" and body["budget_limit_usd"] == 0
    assert body["settings"] == {"aspect_ratio": "9:16", "keep": True, "nested": {"new": 2}}
    null_update = client.patch(
        f"/api/v1/projects/{project['id']}",
        headers=headers,
        json={"name": None, "aspect_ratio": None, "settings": None, "budget_limit_usd": None},
    ).json()
    for field in ("name", "aspect_ratio", "settings", "budget_limit_usd"):
        assert null_update[field] == body[field]


def test_script_identity_keeps_missing_before_authorization_and_patch_defaults(client, headers, project):
    missing = client.get("/api/v1/scripts/missing", headers={"X-User-Id": "intruder"})
    assert missing.status_code == 404
    assert missing.json()["error"]["message"] == "剧本不存在"
    assert missing.json()["error"]["details"] == {"script_id": "missing"}

    saved = client.post(
        f"/api/v1/projects/{project['id']}/scripts",
        headers=headers,
        json={"title": "原稿", "script_text": "保留正文"},
    ).json()
    denied = client.get(f"/api/v1/scripts/{saved['id']}", headers={"X-User-Id": "intruder"})
    assert denied.status_code == 403
    edited = client.patch(
        f"/api/v1/scripts/{saved['id']}",
        headers=headers,
        json={"title": "  新标题  ", "status": "", "content": None},
    )
    assert edited.status_code == 200
    assert edited.json()["title"] == "新标题"
    assert edited.json()["status"] == "edited"
    assert edited.json()["script_text"] == "保留正文"
    assert edited.json()["id"] == saved["id"]
    assert edited.json()["version"] == saved["version"]


def test_document_lookup_rejects_foreign_project_before_enqueuing_parse(client, headers, project):
    other = client.post("/api/v1/projects", json={"name": "另一个项目"}, headers=headers).json()
    imported = client.post(
        f"/api/v1/projects/{other['id']}/upload?sample=true",
        headers=headers,
    ).json()["document"]
    rejected = client.post(
        f"/api/v1/projects/{project['id']}/documents/{imported['id']}/parse",
        headers=headers,
    )
    assert rejected.status_code == 404
    assert rejected.json()["error"]["message"] == "文档不存在"
    assert rejected.json()["error"]["details"] == {"document_id": imported["id"]}
    tasks = client.get(f"/api/v1/projects/{project['id']}/tasks", headers=headers).json()
    assert tasks["count"] == 0


def test_script_details_keep_persisted_event_order_and_history_summary(client, headers, project):
    from studio_platform.persistence.session import session_scope
    from studio_story.infrastructure.persistence.models import StoryEvent

    saved = client.post(
        f"/api/v1/projects/{project['id']}/scripts",
        headers=headers,
        json={"title": "事件投影", "script_text": "独立正文"},
    ).json()
    with session_scope() as db:
        for order in (2, 1):
            db.add(
                StoryEvent(
                    project_id=project["id"],
                    script_id=saved["id"],
                    order_index=order,
                    title=f"事件{order}",
                    character_names=["林简"],
                    importance=0.5,
                )
            )
    detail = client.get(f"/api/v1/scripts/{saved['id']}", headers=headers).json()
    latest = client.get(f"/api/v1/projects/{project['id']}/script", headers=headers).json()
    assert detail == latest
    assert [event["order_index"] for event in detail["events"]] == [1, 2]
    assert [event["character_names"] for event in detail["events"]] == [["林简"], ["林简"]]
    history = client.get(f"/api/v1/projects/{project['id']}/scripts", headers=headers).json()
    assert history["count"] == 1
    assert history["items"][0]["id"] == saved["id"]
    assert history["items"][0]["workspace_meta"] == saved["workspace_meta"]
    assert "events" not in history["items"][0]
