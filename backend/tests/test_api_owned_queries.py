"""HTTP 读取迁入所属模块后，权限、缺失错误、版本排序与 SSE 行为保持。"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from studio_api.api.routes import tasks as task_routes
from studio_characters.infrastructure.persistence.models import Character
from studio_platform.persistence.models import Task
from studio_platform.persistence.session import session_scope
from studio_production.infrastructure.persistence.models import (
    DirectingPlan,
    EditingProject,
    Shot,
    Storyboard,
)
from studio_reviews.infrastructure.persistence.models import Review
from studio_scenes.infrastructure.persistence.models import Scene


@pytest.mark.parametrize(
    ("url", "details"),
    [
        ("/characters/missing", {"character_id": "missing"}),
        ("/scenes/missing", {"scene_id": "missing"}),
        ("/shots/missing", {"shot_id": "missing"}),
        ("/reviews/missing", {"review_id": "missing"}),
        ("/projects/unknown/tasks/missing", {"task_id": "missing"}),
    ],
)
def test_unknown_resource_still_returns_its_404_before_project_authorization(client, url, details):
    response = client.get(f"/api/v1{url}", headers={"X-User-Id": "outsider"})
    assert response.status_code == 404
    assert response.json()["error"]["details"] == details


def test_owned_queries_still_require_project_access_for_existing_resources(client, project):
    pid = project["id"]
    with session_scope() as db:
        rows = [
            Character(project_id=pid, name="林简"),
            Scene(project_id=pid, name="书店"),
            Shot(project_id=pid, storyboard_id="board", order_index=1),
            Review(project_id=pid, stage="shots"),
            Task(project_id=pid, type="video"),
        ]
        db.add_all(rows)
        db.flush()
        urls = [
            f"/characters/{rows[0].id}",
            f"/scenes/{rows[1].id}",
            f"/shots/{rows[2].id}",
            f"/reviews/{rows[3].id}",
            f"/projects/{pid}/tasks/{rows[4].id}",
        ]
    for url in urls:
        response = client.get(f"/api/v1{url}", headers={"X-User-Id": "outsider"})
        assert response.status_code == 403, (url, response.text)
        assert response.json()["error"]["code"] == "permission_denied"


@pytest.mark.parametrize(
    ("model", "endpoint"),
    [(DirectingPlan, "directing"), (Storyboard, "storyboards"), (EditingProject, "editing")],
)
def test_version_queries_keep_descending_order_and_project_scope(client, headers, project, model, endpoint):
    pid = project["id"]
    with session_scope() as db:
        for version in (1, 3, 2):
            db.add(model(project_id=pid, version=version))
        db.add(model(project_id="other-project", version=99))
    response = client.get(f"/api/v1/projects/{pid}/{endpoint}", headers=headers)
    assert response.status_code == 200, response.text
    assert [row["version"] for row in response.json()["versions"]] == [3, 2, 1]


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
def test_event_stream_replays_events_before_terminal_marker_without_extra_polling(monkeypatch, status):
    db = Mock()
    db.get.return_value = SimpleNamespace(id="task", project_id="project", status=status)

    @contextmanager
    def scoped_session():
        yield db

    monkeypatch.setattr(task_routes, "session_scope", scoped_session)
    read_events = Mock(side_effect=[[SimpleNamespace(id="event")], []])
    monkeypatch.setattr(task_routes.task_service, "task_events", read_events)
    monkeypatch.setattr(task_routes.task_service, "sse_payload", lambda event: '{"id":"event"}')

    def forbidden_sleep(*args):
        pytest.fail("终态且已回放事件后不应继续等待")

    monkeypatch.setattr(task_routes.time, "sleep", forbidden_sleep)
    messages = list(task_routes._event_stream("task", "", 10))
    assert messages == [
        ": connected\n\n",
        'event: task\ndata: {"id":"event"}\n\n',
        "event: end\ndata: {}\n\n",
    ]
    assert read_events.call_args_list[0].kwargs["after"] == ""
    assert read_events.call_args_list[1].kwargs["after"] == "event"


def test_deleted_task_in_event_stream_still_times_out_instead_of_raising_404(monkeypatch):
    db = Mock()
    db.get.return_value = None

    @contextmanager
    def scoped_session():
        yield db

    monkeypatch.setattr(task_routes, "session_scope", scoped_session)
    monkeypatch.setattr(task_routes.task_service, "task_events", lambda *args, **kwargs: [])
    clock = iter([0.0, 0.0, 11.0])
    monkeypatch.setattr(task_routes.time, "monotonic", lambda: next(clock))
    assert list(task_routes._event_stream("removed", "", 10)) == [
        ": connected\n\n",
        "event: timeout\ndata: {}\n\n",
    ]
