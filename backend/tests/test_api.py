"""HTTP surface: contracts, isolation, story intake and the admin config API."""

from __future__ import annotations

OTHER_USER = {"X-User-Id": "intruder"}


def test_health_and_meta(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    meta = client.get("/api/v1/meta")
    assert meta.status_code == 200
    payload = meta.json()
    assert payload["agents"]
    assert payload["default_workflow"]
    assert payload["config_versions"]


def test_console_is_served(client):
    index = client.get("/")
    assert index.status_code == 200
    assert "AI Film Studio" in index.text

    script = client.get("/app.js")
    assert script.status_code == 200
    assert "/api/v1" in script.text


def test_project_isolation(client, headers, project):
    own = client.get(f"/api/v1/projects/{project['id']}", headers=headers)
    assert own.status_code == 200

    denied = client.get(f"/api/v1/projects/{project['id']}", headers=OTHER_USER)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "permission_denied"

    listing = client.get("/api/v1/projects", headers=OTHER_USER)
    assert listing.status_code == 200
    assert listing.json()["items"] == []


def test_story_intake_analyze_and_edit(client, headers, project):
    project_id = project["id"]
    upload = client.post(f"/api/v1/projects/{project_id}/upload?sample=true", headers=headers)
    assert upload.status_code == 201, upload.text
    assert len(upload.json()["chapters"]) >= 3

    analyze = client.post(f"/api/v1/projects/{project_id}/analyze?wait=true", headers=headers)
    assert analyze.status_code == 200, analyze.text
    task = analyze.json()["task"]
    assert task["status"] == "succeeded", task
    assert task["result"]

    script = client.get(f"/api/v1/projects/{project_id}/script", headers=headers)
    assert script.status_code == 200
    body = script.json()
    assert body["events"]

    edited = client.patch(
        f"/api/v1/scripts/{body['id']}",
        json={"title": "雨夜书店（导演版）", "status": "edited"},
        headers=headers,
    )
    assert edited.status_code == 200
    assert edited.json()["title"] == "雨夜书店（导演版）"

    characters = client.get(f"/api/v1/projects/{project_id}/characters", headers=headers).json()
    # Characters and scenes belong to the next workflow stage, so a pure script
    # run leaves them empty - the pipeline test covers the populated case.
    assert characters["count"] == 0
    documents = client.get(f"/api/v1/projects/{project_id}/documents", headers=headers).json()
    assert documents["count"] == 1

    # The stream replays history and closes on a finished task.
    stream = client.get(
        f"/api/v1/projects/{project_id}/tasks/{task['id']}/events/stream",
        params={"timeout": 5},
        headers=headers,
    )
    assert stream.status_code == 200
    assert "event: task" in stream.text
    assert "event: end" in stream.text


def test_character_assets_then_approve(client, headers, project):
    project_id = project["id"]
    client.post(f"/api/v1/projects/{project_id}/upload?sample=true", headers=headers)
    # The first gate is parked once characters and scenes exist.
    started = client.post(
        f"/api/v1/projects/{project_id}/workflows/start?wait=true", json={}, headers=headers
    )
    assert started.status_code == 202, started.text
    assert started.json()["task"]["status"] == "succeeded"

    character = client.get(f"/api/v1/projects/{project_id}/characters", headers=headers).json()[
        "items"
    ][0]

    generated = client.post(
        f"/api/v1/characters/{character['id']}/generate-images?wait=true",
        json={"kinds": ["portrait"]},
        headers=headers,
    )
    assert generated.status_code == 200, generated.text
    assert generated.json()["task"]["status"] == "succeeded"

    assets = client.get(f"/api/v1/characters/{character['id']}/assets", headers=headers).json()
    assert assets["count"] >= 1
    url = assets["items"][0]["url"]
    assert url.startswith("/media/")

    media = client.get(url, headers=headers)
    assert media.status_code == 200
    assert media.content

    approved = client.post(f"/api/v1/characters/{character['id']}/approve", headers=headers)
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_dashboard_summarises_a_fresh_project(client, headers, project):
    dashboard = client.get(f"/api/v1/projects/{project['id']}/dashboard", headers=headers)
    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body["project"]["id"] == project["id"]
    assert body["summary"]["shot_count"] == 0
    assert body["workflow"] is None
    assert body["tasks"] == []


def test_admin_config_versions_round_trip(client, headers):
    listing = client.get("/api/v1/admin/model-configs", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["count"] >= 13

    current = client.get("/api/v1/admin/model-configs/script", headers=headers)
    assert current.status_code == 200
    payload = current.json()["payload"]
    assert payload["agent"]["id"] == "script"

    payload["generation"]["temperature"] = 0.9
    created = client.post(
        "/api/v1/admin/model-configs/script/versions",
        json={"payload": payload, "note": "tests: raise temperature"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["version"]["version"] == 1
    assert created.json()["applied"]["generation"]["temperature"] == 0.9

    # A second change makes the first version rollback-able.
    payload["generation"]["temperature"] = 0.1
    second = client.post(
        "/api/v1/admin/model-configs/script/versions",
        json={"payload": payload, "note": "tests: lower temperature"},
        headers=headers,
    )
    assert second.json()["version"]["version"] == 2

    rollback = client.post("/api/v1/admin/model-configs/script/rollback", headers=headers)
    assert rollback.status_code == 200
    assert rollback.json()["applied"]["generation"]["temperature"] == 0.9

    reset = client.delete("/api/v1/admin/model-configs/script/override", headers=headers)
    assert reset.status_code == 200
    assert reset.json()["applied"]["generation"]["temperature"] == 0.3

    forbidden = client.get(
        "/api/v1/admin/model-configs",
        headers={"X-User-Id": "tester", "X-User-Role": "user"},
    )
    assert forbidden.status_code == 403


def test_validation_errors_use_the_error_envelope(client, headers):
    response = client.post("/api/v1/projects", json={"name": ""}, headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

    missing = client.get("/api/v1/projects/does-not-exist", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
