"""Task queue / event log.

Tasks are the only long-running entry point: HTTP handlers create a ``Task`` row,
return its id, and a worker executes it in its own session.  Progress is written
to ``task_events`` so the SSE endpoint can stream it without any in-process
pub/sub (which would not survive multiple workers).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config_models import WorkflowNodeConfig
from app.core.constants import TaskStatus
from app.core.exceptions import NotFoundError, ValidationAppError
from app.core.ids import new_id, utcnow
from app.db.session import session_scope
from app.models.ops import Task, TaskEvent
from app.models.project import Project
from app.services.agent_runner import json_safe
from app.services.runtime import AppRuntime

logger = logging.getLogger(__name__)

TaskHandler = Callable[[Session, AppRuntime, Task], Awaitable[dict[str, Any] | None]]

STAGE_TASKS = {
    "script",
    "characters",
    "scenes",
    "directing",
    "storyboard",
    "character_assets",
    "video",
    "audio",
    "editing",
    "render",
    "evaluation",
    "export",
}


# ------------------------------------------------------------------- records
def create_task(
    db: Session,
    *,
    project: Project,
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
            select(Task)
            .where(Task.project_id == project_id)
            .order_by(Task.created_at.desc())
            .limit(limit)
        )
    )


def task_events(
    db: Session, task_id: str, *, after: str = "", limit: int = 500
) -> list[TaskEvent]:
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


# -------------------------------------------------------------------- runner
class TaskRunner:
    """Thread-based runner: one short-lived session and event loop per task."""

    def __init__(self, *, max_workers: int = 4, inline: bool = True) -> None:
        self.inline = inline
        self.max_workers = max(1, int(max_workers))
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="task")
        self._cancelled: set[str] = set()
        self._threads: dict[str, threading.Thread] = {}
        self._done: dict[str, threading.Event] = {}
        self._futures: dict[str, Future] = {}
        self._lock = threading.RLock()

    # -- submission
    def submit(self, task_id: str, handler: TaskHandler, runtime: AppRuntime) -> None:
        done = threading.Event()
        with self._lock:
            self._done[task_id] = done
        if self.inline:
            thread = threading.Thread(
                target=self._worker,
                args=(task_id, handler, runtime, done),
                name=f"task-{task_id[-6:]}",
                daemon=True,
            )
            with self._lock:
                self._threads[task_id] = thread
            thread.start()
        else:
            future = self._executor.submit(self._worker, task_id, handler, runtime, done)
            with self._lock:
                self._futures[task_id] = future

    def wait(self, task_id: str, timeout: float | None = 60.0) -> bool:
        with self._lock:
            done = self._done.get(task_id)
        return bool(done and done.wait(timeout))

    def is_cancelled(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._cancelled

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._done and not self._done[task_id].is_set():
                self._cancelled.add(task_id)
                return True
        return False

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -- worker
    def _worker(
        self,
        task_id: str,
        handler: TaskHandler,
        runtime: AppRuntime,
        done: threading.Event,
    ) -> None:
        try:
            with session_scope() as db:
                task = db.get(Task, task_id)
                if task is None:  # pragma: no cover - defensive
                    return
                if self.is_cancelled(task_id):
                    task.status = TaskStatus.CANCELLED.value
                    task.finished_at = utcnow()
                    db.flush()
                    return
                task.status = TaskStatus.RUNNING.value
                task.started_at = utcnow()
                task.attempts = int(task.attempts or 0) + 1
                task.error = ""
                task.config_versions = dict(runtime.config_store.config_versions())
                emit(db, task, "started", f"任务开始：{task.type}", progress=0.0)
                db.commit()

                try:
                    result = asyncio.run(handler(db, runtime, task))
                except Exception as exc:
                    db.rollback()
                    task = db.get(Task, task_id)
                    if task is None:  # pragma: no cover
                        return
                    task.status = TaskStatus.FAILED.value
                    task.error = f"{type(exc).__name__}: {exc}"[:4000]
                    task.finished_at = utcnow()
                    task.message = "任务失败"
                    emit(
                        db,
                        task,
                        "failed",
                        task.error,
                        level="error",
                        data={"type": type(exc).__name__},
                    )
                    db.commit()
                    logger.warning("task %s failed: %s", task_id, exc)
                    return

                task = db.get(Task, task_id)
                if task is None:  # pragma: no cover
                    return
                if self.is_cancelled(task_id):
                    task.status = TaskStatus.CANCELLED.value
                    task.message = "任务已取消"
                else:
                    task.status = TaskStatus.SUCCEEDED.value
                    task.progress = 1.0
                    task.message = task.message or "任务完成"
                    task.result = json_safe(result or {})
                task.finished_at = utcnow()
                emit(
                    db,
                    task,
                    "completed" if task.status == TaskStatus.SUCCEEDED.value else "cancelled",
                    task.message,
                    progress=task.progress,
                )
                db.commit()
        except Exception:  # pragma: no cover - session/commit failures
            logger.exception("task runner crashed for %s", task_id)
        finally:
            with self._lock:
                self._cancelled.discard(task_id)
                self._threads.pop(task_id, None)
                self._futures.pop(task_id, None)
            done.set()


_runner_lock = threading.RLock()


def get_runner(runtime: AppRuntime) -> TaskRunner:
    """One runner per runtime so tests can isolate task execution."""
    if runtime.task_runner is not None:
        return runtime.task_runner
    with _runner_lock:
        if runtime.task_runner is None:
            runtime.task_runner = TaskRunner(
                max_workers=runtime.settings.max_workers, inline=runtime.settings.inline_tasks
            )
            runtime.extras["is_cancelled"] = runtime.task_runner.is_cancelled
        return runtime.task_runner


def reset_runner(runtime: AppRuntime | None = None) -> None:
    if runtime is not None and runtime.task_runner is not None:
        runtime.task_runner.shutdown()
        runtime.task_runner = None
        runtime.extras.pop("is_cancelled", None)


# ------------------------------------------------------------------ handlers
def build_handler(task: Task, runtime: AppRuntime) -> TaskHandler:
    """Turn a task type/payload into an async callable."""
    if task.type == "workflow":
        return _workflow_handler(task.payload or {})
    if task.type == "workflow_resume":
        return _resume_handler(task.payload or {})
    if task.type in STAGE_TASKS:
        # The task type *is* the handler name, which keeps the stage router and
        # the workflow YAML vocabulary identical.
        return _stage_handler(task.type)
    if task.type == "shot_video":
        return _shot_video_handler(task.payload or {})
    if task.type == "character_images":
        return _character_images_handler(task.payload or {})
    if task.type == "parse_document":
        return _parse_document_handler(task.payload or {})
    if task.type == "cancel_workflow":
        return _cancel_workflow_handler(task.payload or {})
    raise ValidationAppError(f"未知任务类型 '{task.type}'")


def _workflow_handler(payload: dict[str, Any]) -> TaskHandler:
    async def handler(db: Session, runtime: AppRuntime, task: Task) -> dict[str, Any]:
        from app.services.workflow import WorkflowEngine

        project = db.get(Project, task.project_id)
        if project is None:
            raise NotFoundError("项目不存在", details={"project_id": task.project_id})
        engine = WorkflowEngine(runtime)
        run = await engine.start(
            db,
            project=project,
            workflow_id=payload.get("workflow_id"),
            task=task,
            user_id=task.created_by,
        )
        task.workflow_run_id = run.id
        return {"workflow_run_id": run.id, "status": run.status}

    return handler


def _resume_handler(payload: dict[str, Any]) -> TaskHandler:
    async def handler(db: Session, runtime: AppRuntime, task: Task) -> dict[str, Any]:
        from app.services.workflow import WorkflowEngine, get_run

        project = db.get(Project, task.project_id)
        run = get_run(db, task.project_id, str(payload.get("workflow_run_id") or ""))
        engine = WorkflowEngine(runtime)
        run = await engine.resume(db, run=run, project=project, task=task, user_id=task.created_by)
        return {"workflow_run_id": run.id, "status": run.status}

    return handler


def _stage_handler(stage: str) -> TaskHandler:
    async def handler(db: Session, runtime: AppRuntime, task: Task) -> dict[str, Any]:
        from app.services.workflow_handlers import HandlerContext, require_handler

        project = db.get(Project, task.project_id)
        if project is None:
            raise NotFoundError("项目不存在", details={"project_id": task.project_id})
        node = WorkflowNodeConfig(id=stage, type="handler", handler=stage, title=stage)
        ctx = HandlerContext(
            db=db,
            runtime=runtime,
            project=project,
            task=task,
            workflow_run=None,
            node=node,
            user_id=task.created_by,
            stop=lambda: get_runner(runtime).is_cancelled(task.id),
        )
        return await require_handler(stage)(ctx)

    return handler


def _shot_video_handler(payload: dict[str, Any]) -> TaskHandler:
    """Regenerate a single shot without touching the rest of the storyboard."""

    async def handler(db: Session, runtime: AppRuntime, task: Task) -> dict[str, Any]:
        from app.models.production import Shot
        from app.services import media

        project = db.get(Project, task.project_id)
        if project is None:
            raise NotFoundError("项目不存在", details={"project_id": task.project_id})
        shot = db.get(Shot, str(payload.get("shot_id") or ""))
        if shot is None or shot.project_id != project.id:
            raise NotFoundError("镜头不存在", details=payload)
        return await media.generate_shot_videos(
            db,
            runtime,
            project=project,
            shots=[shot],
            task=task,
            user_id=task.created_by,
            stop=lambda: get_runner(runtime).is_cancelled(task.id),
        )

    return handler


def _character_images_handler(payload: dict[str, Any]) -> TaskHandler:
    """Generate (or regenerate) character images for one character."""

    async def handler(db: Session, runtime: AppRuntime, task: Task) -> dict[str, Any]:
        from app.models.character import Character
        from app.services import media

        project = db.get(Project, task.project_id)
        if project is None:
            raise NotFoundError("项目不存在", details={"project_id": task.project_id})
        character = db.get(Character, str(payload.get("character_id") or ""))
        if character is None or character.project_id != project.id:
            raise NotFoundError("人物不存在", details=payload)
        kinds = tuple(payload.get("kinds") or media.CHARACTER_ASSET_KINDS)
        return await media.generate_character_assets(
            db,
            runtime,
            project=project,
            characters=[character],
            kinds=kinds,
            task=task,
            user_id=task.created_by,
            stop=lambda: get_runner(runtime).is_cancelled(task.id),
        )

    return handler


def _parse_document_handler(payload: dict[str, Any]) -> TaskHandler:
    async def handler(db: Session, runtime: AppRuntime, task: Task) -> dict[str, Any]:
        from app.models.story import SourceDocument
        from app.services import documents

        document = db.get(SourceDocument, str(payload.get("document_id") or ""))
        if document is None:
            raise NotFoundError("文档不存在", details=payload)
        chapters = documents.parse_document(db, runtime, document)
        return {"document_id": document.id, "chapters": len(chapters)}

    return handler


def _cancel_workflow_handler(payload: dict[str, Any]) -> TaskHandler:
    async def handler(db: Session, runtime: AppRuntime, task: Task) -> dict[str, Any]:
        from app.services.workflow import cancel, get_run

        run = get_run(db, task.project_id, str(payload.get("workflow_run_id") or ""))
        cancel(db, run)
        return {"workflow_run_id": run.id, "status": run.status}

    return handler


# ------------------------------------------------------------------- facade
def enqueue(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    type: str,
    payload: dict[str, Any] | None = None,
    user_id: str = "",
    workflow_run_id: str = "",
) -> Task:
    """Create the task row, commit it, then hand it to the runner."""
    task = create_task(
        db,
        project=project,
        type=type,
        payload=payload or {},
        user_id=user_id,
        workflow_run_id=workflow_run_id,
    )
    db.commit()
    runner = get_runner(runtime)
    runner.submit(task.id, build_handler(task, runtime), runtime)
    return task


def cancel_task(db: Session, runtime: AppRuntime, task: Task) -> Task:
    if task.status not in {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}:
        raise ValidationAppError("只有排队中或运行中的任务可以取消")
    get_runner(runtime).cancel(task.id)
    task.status = TaskStatus.CANCELLED.value
    task.finished_at = utcnow()
    emit(db, task, "cancelled", "任务已取消")
    db.flush()
    return task


def sse_payload(event: TaskEvent) -> str:
    return json.dumps(event_public(event), ensure_ascii=False)
