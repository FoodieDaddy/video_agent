"""Task inspection, cancellation and the SSE event stream."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.api.deps import RuntimeDep, SessionDep, UserDep, project_scope
from app.models.ops import Task
from app.modules.platform.persistence.session import session_scope
from app.modules.workflow.public import tasks as task_service

router = APIRouter(prefix="/projects/{project_id}/tasks", tags=["tasks"])

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
POLL_SECONDS = 0.4
KEEPALIVE_SECONDS = 15.0


@router.get("")
def list_tasks(
    project_id: str,
    db: SessionDep,
    user: UserDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = task_service.list_tasks(db, project.id, limit=limit)
    return {"items": [task_service.task_public(row) for row in rows], "count": len(rows)}


@router.get("/{task_id}")
def get_task(task_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project_id = project_id_of(db, task_id)
    project_scope(db, project_id, user)
    task = task_service.get_task(db, project_id, task_id)
    return {
        "task": task_service.task_public(task),
        "events": [
            task_service.event_public(event) for event in task_service.task_events(db, task.id, limit=200)
        ],
    }


@router.get("/{task_id}/events")
def list_events(
    task_id: str,
    db: SessionDep,
    user: UserDep,
    after: str = "",
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    project_id = project_id_of(db, task_id)
    project_scope(db, project_id, user)
    rows = task_service.task_events(db, task_id, after=after, limit=limit)
    return {"items": [task_service.event_public(row) for row in rows], "count": len(rows)}


@router.get("/{task_id}/events/stream")
def stream_events(
    task_id: str,
    db: SessionDep,
    user: UserDep,
    after: str = "",
    timeout: float = Query(default=900.0, ge=5.0, le=3600.0),
) -> StreamingResponse:
    """Server-sent events: existing history first, then live progress.

    Events are read back from ``task_events`` instead of an in-process bus, so
    the stream also works when the worker lives in another process.
    """
    project_id = project_id_of(db, task_id)
    project_scope(db, project_id, user)
    task_service.get_task(db, project_id, task_id)
    return StreamingResponse(
        _event_stream(task_id, after, timeout),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str, runtime: RuntimeDep, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project_id = project_id_of(db, task_id)
    project = project_scope(db, project_id, user)
    task = task_service.get_task(db, project.id, task_id)
    updated = task_service.cancel_task(db, runtime, task)
    db.flush()
    return {"task": task_service.task_public(updated)}


def _event_stream(task_id: str, after: str, timeout: float) -> Iterator[str]:
    cursor = after
    deadline = time.monotonic() + timeout
    last_beat = time.monotonic()
    yield ": connected\n\n"
    while True:
        events = []
        finished = False
        with session_scope() as session:
            events = task_service.task_events(session, task_id, after=cursor, limit=200)
            task = session.get(Task, task_id)
            finished = task is not None and task.status in TERMINAL_STATUSES
        if events:
            for event in events:
                cursor = event.id
                yield f"event: task\ndata: {task_service.sse_payload(event)}\n\n"
            last_beat = time.monotonic()
            continue
        if finished:
            yield "event: end\ndata: {}\n\n"
            return
        if time.monotonic() > deadline:
            yield "event: timeout\ndata: {}\n\n"
            return
        if time.monotonic() - last_beat > KEEPALIVE_SECONDS:
            yield ": keep-alive\n\n"
            last_beat = time.monotonic()
        time.sleep(POLL_SECONDS)


def project_id_of(db, task_id: str) -> str:
    """Resolve a task's project so the usual isolation check can run."""
    from app.modules.platform.exceptions import NotFoundError

    task = db.get(Task, task_id)
    if task is None:
        raise NotFoundError("任务不存在", details={"task_id": task_id})
    return task.project_id
