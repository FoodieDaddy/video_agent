"""End-to-end run through the HTTP API: gates, artifacts, render and export."""

from __future__ import annotations

EXPECTED_STAGES = ["characters_scenes", "storyboard", "shots", "final"]


def pending_reviews(client, headers, project_id):
    dashboard = client.get(f"/api/v1/projects/{project_id}/dashboard", headers=headers).json()
    return dashboard, dashboard.get("pending_reviews") or []


def test_workflow_runs_to_completion_with_human_gates(client, headers, project):
    project_id = project["id"]
    upload = client.post(f"/api/v1/projects/{project_id}/upload?sample=true", headers=headers)
    assert upload.status_code == 201

    started = client.post(
        f"/api/v1/projects/{project_id}/workflows/start?wait=true",
        json={},
        headers=headers,
    )
    assert started.status_code == 202, started.text
    workflow_task = started.json()["task"]
    assert workflow_task["status"] == "succeeded", workflow_task

    stages: list[str] = []
    for _ in range(8):
        _, pending = pending_reviews(client, headers, project_id)
        if not pending:
            break
        review = pending[0]
        stages.append(review["stage"])
        decided = client.post(
            f"/api/v1/reviews/{review['id']}?wait=true",
            json={"status": "approved", "comment": "自动化审核通过"},
            headers=headers,
        )
        assert decided.status_code == 200, decided.text

    dashboard, pending = pending_reviews(client, headers, project_id)
    assert pending == []
    assert dashboard["workflow"]["status"] == "completed", dashboard["workflow"]
    assert stages == EXPECTED_STAGES

    shots = client.get(f"/api/v1/projects/{project_id}/shots", headers=headers).json()
    assert shots["count"] >= 3
    for shot in shots["items"]:
        assert shot["approved"] is True
        versions = client.get(f"/api/v1/shots/{shot['id']}/versions", headers=headers).json()
        assert versions["count"] >= 1
        assert versions["items"][0]["url"]

    audio = client.get(f"/api/v1/projects/{project_id}/audio", headers=headers).json()
    assert audio["count"] >= 1

    editing = client.get(f"/api/v1/projects/{project_id}/editing", headers=headers).json()
    assert editing["editing"]["output_url"]
    assert editing["editing"]["duration_seconds"] > 0

    evaluation = client.get(f"/api/v1/projects/{project_id}/evaluation", headers=headers).json()
    assert 0.0 <= evaluation["evaluation"]["overall_score"] <= 1.0
    assert evaluation["evaluation"]["recommendation"] in {"accept", "review", "reject"}

    export = client.get(f"/api/v1/projects/{project_id}/export", headers=headers).json()
    assert export["ready"] is True
    film = client.get(export["film"]["url"], headers=headers)
    assert film.status_code == 200
    assert len(film.content) > 1000

    final = client.get(f"/api/v1/projects/{project_id}", headers=headers).json()
    assert final["status"] == "completed"

    # The finished workflow task replays its history and closes the stream.
    stream = client.get(
        f"/api/v1/projects/{project_id}/tasks/{workflow_task['id']}/events/stream",
        params={"timeout": 5},
        headers=headers,
    )
    assert "event: end" in stream.text
