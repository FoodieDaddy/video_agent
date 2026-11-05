"""任务业务分派与兼容入口；平台运行器不依赖这些业务处理器。

具体业务能力在处理器内部延迟通过公开接口加载，避免模块装配时形成循环。
Task/事件记录和运行器符号仍在这里重新导出，保持旧 services.tasks 的公开入口。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.modules.platform.configuration.config_models import WorkflowNodeConfig
from app.modules.platform.constants import TaskStatus
from app.modules.platform.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.modules.platform.execution.runtime import AppRuntime
from app.modules.platform.execution.task_runner import (
    TaskHandler,
    TaskRunner,
    get_runner,
    reset_runner,
)
from app.modules.platform.ids import utcnow
from app.modules.platform.persistence.models import Task
from app.modules.platform.persistence.task_records import (
    create_task,
    emit,
    event_public,
    get_task,
    list_tasks,
    sse_payload,
    task_events,
    task_public,
)
from app.modules.projects.contracts import ProjectContext as Project
from app.modules.projects.public import find_project_context

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


def build_handler(task: Task, runtime: AppRuntime) -> TaskHandler:
    """Turn a task type/payload into an async callable."""
    if task.type == "workflow":
        return _workflow_handler(task.payload or {})
    if task.type == "workflow_resume":
        return _resume_handler(task.payload or {})
    if task.type == "script_assist":
        return _script_assist_handler(task.payload or {})
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


def _script_assist_handler(payload: dict[str, Any]) -> TaskHandler:
    """通过story公开用例执行单次AI编辑，不进入整条生产工作流。"""

    async def handler(db: Session, runtime: AppRuntime, task: Task) -> dict[str, Any]:
        from app.modules.story import public as story

        project = find_project_context(db, task.project_id)
        if project is None:
            raise NotFoundError("项目不存在", details={"project_id": task.project_id})
        try:
            script = await story.revise_script(
                db,
                runtime,
                project=project,
                base_script_id=str(payload.get("base_script_id") or ""),
                operation=str(payload.get("operation") or ""),
                instruction=str(payload.get("instruction") or ""),
                task=task,
                user_id=task.created_by,
            )
        except ConflictError as exc:
            # 此标记只用于模型完成后、创建Script之前的基线检查。将已产生的
            # 模型审计/费用提交，再由运行器把任务记失败；不谎称其他异常也独立持久化。
            if exc.details.get("generation_completed") is True:
                db.commit()
            raise
        return {
            "script_id": script.id,
            "version": script.version,
            "operation": payload["operation"],
            "status": script.status,
            "requires_reconfirmation": True,
        }

    return handler


def _workflow_handler(payload: dict[str, Any]) -> TaskHandler:
    async def handler(db: Session, runtime: AppRuntime, task: Task) -> dict[str, Any]:
        from app.modules.workflow.public import WorkflowEngine

        project = find_project_context(db, task.project_id)
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
        from app.modules.workflow.public import WorkflowEngine, get_run

        project = find_project_context(db, task.project_id)
        run = get_run(db, task.project_id, str(payload.get("workflow_run_id") or ""))
        engine = WorkflowEngine(runtime)
        run = await engine.resume(db, run=run, project=project, task=task, user_id=task.created_by)
        return {"workflow_run_id": run.id, "status": run.status}

    return handler


def _stage_handler(stage: str) -> TaskHandler:
    async def handler(db: Session, runtime: AppRuntime, task: Task) -> dict[str, Any]:
        from app.modules.workflow.public import HandlerContext, require_handler

        project = find_project_context(db, task.project_id)
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
        from app.modules.production import public as media

        project = find_project_context(db, task.project_id)
        if project is None:
            raise NotFoundError("项目不存在", details={"project_id": task.project_id})
        return await media.generate_shot_video_by_id(
            db,
            runtime,
            project=project,
            shot_id=str(payload.get("shot_id") or ""),
            task=task,
            user_id=task.created_by,
            stop=lambda: get_runner(runtime).is_cancelled(task.id),
        )

    return handler


def _character_images_handler(payload: dict[str, Any]) -> TaskHandler:
    """Generate (or regenerate) character images for one character."""

    async def handler(db: Session, runtime: AppRuntime, task: Task) -> dict[str, Any]:
        from app.modules.characters.public import find_character_reference
        from app.modules.production import public as media

        project = find_project_context(db, task.project_id)
        if project is None:
            raise NotFoundError("项目不存在", details={"project_id": task.project_id})
        character = find_character_reference(db, project.id, str(payload.get("character_id") or ""))
        if character is None:
            raise NotFoundError("人物不存在", details=payload)
        kinds = tuple(payload.get("kinds") or media.CHARACTER_ASSET_KINDS)
        return await media.generate_character_assets(
            db,
            runtime,
            project=project,
            character_ids=[character.id],
            kinds=kinds,
            task=task,
            user_id=task.created_by,
            stop=lambda: get_runner(runtime).is_cancelled(task.id),
        )

    return handler


def _parse_document_handler(payload: dict[str, Any]) -> TaskHandler:
    async def handler(db: Session, runtime: AppRuntime, task: Task) -> dict[str, Any]:
        from app.modules.story import public as documents

        return documents.parse_project_document(
            db, runtime, project_id=task.project_id, document_id=str(payload.get("document_id") or "")
        )

    return handler


def _cancel_workflow_handler(payload: dict[str, Any]) -> TaskHandler:
    async def handler(db: Session, runtime: AppRuntime, task: Task) -> dict[str, Any]:
        from app.modules.workflow.public import cancel, get_run

        run = get_run(db, task.project_id, str(payload.get("workflow_run_id") or ""))
        cancel(db, run)
        return {"workflow_run_id": run.id, "status": run.status}

    return handler


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


__all__ = [
    "STAGE_TASKS",
    "TaskHandler",
    "TaskRunner",
    "build_handler",
    "cancel_task",
    "create_task",
    "emit",
    "enqueue",
    "event_public",
    "get_runner",
    "get_task",
    "list_tasks",
    "reset_runner",
    "sse_payload",
    "task_events",
    "task_public",
]
