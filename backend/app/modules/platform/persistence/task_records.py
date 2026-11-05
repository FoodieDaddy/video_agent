"""任务与事件持久化；不负责线程执行或选择业务处理器。

迁移当前 ORM 查询与序列化行为，事务仍由调用方管理。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.contracts.public import ProjectIdentity, json_safe
from app.modules.platform.constants import TaskStatus
from app.modules.platform.exceptions import NotFoundError
from app.modules.platform.ids import new_id
from app.modules.platform.persistence.models import Task, TaskEvent


def create_task(
    db: Session,
    *,
    project: ProjectIdentity,
    type: str,
    payload: dict[str, Any] | None = None,
    user_id: str = "",
    workflow_run_id: str = "",
    max_attempts: int = 3,
) -> Task:
    task = Task(
        id=new_id("task"),
        project_id=project.id,
        workflow_run_id=workflow_run_id,
        type=type,
        status=TaskStatus.PENDING.value,
        payload=payload or {},
        max_attempts=max_attempts,
        created_by=user_id,
        config_versions={},
    )
    db.add(task)
    db.flush()
    return task


def emit(
    db: Session,
    task: Task,
    event_type: str = "progress",
    message: str = "",
    *,
    progress: float | None = None,
    data: dict[str, Any] | None = None,
    level: str = "info",
) -> TaskEvent:
    event = TaskEvent(
        id=new_id("tevent"),
        task_id=task.id,
        project_id=task.project_id,
        level=level,
        event_type=event_type,
        message=message[:4000],
        progress=float(task.progress if progress is None else progress),
        data=json_safe(data or {}),
    )
    db.add(event)
    db.flush()
    return event


def get_task(db: Session, project_id: str, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.project_id != project_id:
        raise NotFoundError("任务不存在", details={"task_id": task_id})
    return task


def list_tasks(db: Session, project_id: str, *, limit: int = 50) -> list[Task]:
    return list(
        db.scalars(
            select(Task).where(Task.project_id == project_id).order_by(Task.created_at.desc()).limit(limit)
        )
    )


def task_events(db: Session, task_id: str, *, after: str = "", limit: int = 500) -> list[TaskEvent]:
    statement = select(TaskEvent).where(TaskEvent.task_id == task_id)
    if after:
        anchor = db.get(TaskEvent, after)
        if anchor is not None:
            statement = statement.where(TaskEvent.created_at >= anchor.created_at).where(
                TaskEvent.id != anchor.id
            )
    return list(db.scalars(statement.order_by(TaskEvent.created_at).limit(limit)))


def task_public(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "project_id": task.project_id,
        "workflow_run_id": task.workflow_run_id,
        "type": task.type,
        "status": task.status,
        "stage": task.stage,
        "progress": task.progress,
        "message": task.message,
        "payload": task.payload or {},
        "result": task.result or {},
        "error": task.error,
        "attempts": task.attempts,
        "max_attempts": task.max_attempts,
        "config_versions": task.config_versions or {},
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


def event_public(event: TaskEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "task_id": event.task_id,
        "event_type": event.event_type,
        "level": event.level,
        "message": event.message,
        "progress": event.progress,
        "data": event.data or {},
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def sse_payload(event: TaskEvent) -> str:
    return json.dumps(event_public(event), ensure_ascii=False)
