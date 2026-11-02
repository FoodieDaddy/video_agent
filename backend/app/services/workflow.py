"""Workflow engine (in-house, persisted, resumable).

The engine is deliberately small and explicit instead of hiding control flow in
a graph library:

* the workflow definition is YAML (``config/workflows/*.yaml``);
* every node execution writes a ``workflow_checkpoints`` row;
* a ``gate`` node creates a ``Review`` and parks the run in ``awaiting_review``;
* approving the review and calling :meth:`WorkflowEngine.resume` continues from
  the exact node index stored on the run — no replay, no lost work.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config_models import WorkflowConfig, WorkflowNodeConfig
from app.core.constants import WorkflowStatus
from app.core.exceptions import ValidationAppError, WorkflowError
from app.core.ids import new_id, utcnow
from app.models.ops import Task, WorkflowCheckpoint, WorkflowRun
from app.models.project import Project
from app.services import reviews
from app.services.runtime import AppRuntime
from app.services.workflow_handlers import HandlerContext, build_handlers, require_handler

logger = logging.getLogger(__name__)


class WorkflowEngine:
    def __init__(self, runtime: AppRuntime) -> None:
        self.runtime = runtime
        self.handlers = build_handlers()

    # ------------------------------------------------------------- lifecycle
    async def start(
        self,
        db: Session,
        *,
        project: Project,
        workflow_id: str | None = None,
        task: Task | None = None,
        user_id: str = "",
    ) -> WorkflowRun:
        workflow = self.runtime.config_store.workflow(
            workflow_id or self.runtime.config_store.default_workflow_id()
        )
        if not workflow.nodes:
            raise WorkflowError(f"工作流 '{workflow.id}' 没有节点")
        active = db.scalar(
            select(WorkflowRun).where(
                WorkflowRun.project_id == project.id,
                WorkflowRun.definition_id == workflow.id,
                WorkflowRun.status.in_(
                    [
                        WorkflowStatus.RUNNING.value,
                        WorkflowStatus.AWAITING_REVIEW.value,
                        WorkflowStatus.PENDING.value,
                    ]
                ),
            )
        )
        if active is not None:
            raise ValidationAppError(
                "该项目已有进行中的工作流，请先完成或取消",
                details={"workflow_run_id": active.id, "status": active.status},
            )

        run = WorkflowRun(
            id=new_id("run"),
            project_id=project.id,
            definition_id=workflow.id,
            definition_version=workflow.version,
            status=WorkflowStatus.RUNNING.value,
            state={
                "next_index": 0,
                "outputs": {},
                "workflow_config_version": workflow.config_version,
            },
            config_versions={
                **self.runtime.config_store.config_versions(),
                "workflow": workflow.config_version,
            },
            task_id=task.id if task else "",
            started_at=utcnow(),
        )
        db.add(run)
        db.flush()
        logger.info("workflow %s started for project %s", workflow.id, project.id)
        return await self.run(db, run=run, project=project, task=task, user_id=user_id)

    async def resume(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        project: Project,
        task: Task | None = None,
        user_id: str = "",
    ) -> WorkflowRun:
        if run.status not in {
            WorkflowStatus.AWAITING_REVIEW.value,
            WorkflowStatus.FAILED.value,
            WorkflowStatus.PENDING.value,
        }:
            raise WorkflowError(
                f"工作流当前状态为 {run.status}，无法恢复",
                details={"workflow_run_id": run.id},
            )
        run.status = WorkflowStatus.RUNNING.value
        run.error = ""
        run.task_id = task.id if task else run.task_id
        db.flush()
        return await self.run(db, run=run, project=project, task=task, user_id=user_id)

    async def run(
        self,
        db: Session,
        *,
        run: WorkflowRun,
        project: Project,
        task: Task | None = None,
        user_id: str = "",
        workflow: WorkflowConfig | None = None,
    ) -> WorkflowRun:
        workflow = workflow or self.runtime.config_store.workflow(run.definition_id)
        nodes = workflow.nodes
        # ``state`` is mutated in place, so it must always be written back as a
        # *copy*: assigning the same dict object again is invisible to
        # SQLAlchemy and the run would resume from a stale cursor.
        state = dict(run.state or {})
        index = int(state.get("next_index") or 0)

        while index < len(nodes):
            node = nodes[index]
            run.current_node = node.id
            db.flush()

            if node.type == "gate":
                try:
                    outcome = self._handle_gate(db, run=run, project=project, node=node)
                except Exception as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    run.status = WorkflowStatus.FAILED.value
                    run.error = message[:4000]
                    run.finished_at = utcnow()
                    self._checkpoint(
                        db, run, node, status="failed", error=message[:2000],
                        summary=f"审核关卡失败：{node.title or node.id}",
                    )
                    state["next_index"] = index
                    run.state = dict(state)
                    db.commit()
                    raise
                if outcome == "awaiting":
                    state["next_index"] = index
                    run.state = dict(state)
                    self._checkpoint(
                        db,
                        run,
                        node,
                        status="awaiting_review",
                        summary=f"等待人工审核：{node.title or node.review_stage}",
                    )
                    run.status = WorkflowStatus.AWAITING_REVIEW.value
                    if task is not None:
                        task.stage = node.id
                        task.message = f"等待审核：{node.title or node.review_stage}"
                    db.commit()
                    return run
                index += 1
                state["next_index"] = index
                run.state = dict(state)
                run.awaiting_stage = ""
                run.pending_review_id = ""
                self._checkpoint(
                    db,
                    run,
                    node,
                    status="completed",
                    summary=f"审核通过：{node.review_stage}",
                )
                self._progress(task, index, len(nodes), node)
                db.commit()
                continue

            handler_name = node.handler or node.agent or ""
            handler = self.handlers.get(handler_name)
            if handler is None:
                handler = require_handler(handler_name)  # raises a descriptive error

            ctx = HandlerContext(
                db=db,
                runtime=self.runtime,
                project=project,
                task=task,
                workflow_run=run,
                node=node,
                user_id=user_id,
                stop=self._stop_check(task),
            )
            logger.info("workflow %s node %s -> handler %s", run.id, node.id, handler_name)
            try:
                output = await handler(ctx) or {}
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                if node.continue_on_error:
                    logger.warning("node %s failed but continues: %s", node.id, message)
                    self._checkpoint(
                        db,
                        run,
                        node,
                        status="failed",
                        error=message[:2000],
                        summary=f"{node.title or node.id} 失败，按配置继续",
                    )
                    index += 1
                    state["next_index"] = index
                    state.setdefault("outputs", {})[node.id] = {"error": message}
                    run.state = dict(state)
                    self._progress(task, index, len(nodes), node)
                    db.commit()
                    continue

                run.status = WorkflowStatus.FAILED.value
                run.error = message[:4000]
                run.finished_at = utcnow()
                self._checkpoint(
                    db, run, node, status="failed", error=message[:2000],
                    summary=f"{node.title or node.id} 失败",
                )
                state["next_index"] = index
                run.state = dict(state)
                db.commit()
                logger.exception("workflow %s failed at node %s", run.id, node.id)
                raise

            index += 1
            state["next_index"] = index
            state.setdefault("outputs", {})[node.id] = output
            run.state = dict(state)
            self._checkpoint(
                db,
                run,
                node,
                status="completed",
                summary=_summary(node, output),
                output=output,
            )
            self._progress(task, index, len(nodes), node)
            db.commit()

        run.status = WorkflowStatus.COMPLETED.value
        run.current_node = ""
        run.awaiting_stage = ""
        run.pending_review_id = ""
        run.finished_at = utcnow()
        db.commit()
        logger.info("workflow run %s completed for project %s", run.id, project.id)
        return run

    # --------------------------------------------------------------- helpers
    def _stop_check(self, task: Task | None):
        """Expose the runner's cancellation flag to long media loops."""
        checker = (self.runtime.extras or {}).get("is_cancelled")
        if task is None or not callable(checker):
            return None
        task_id = task.id
        return lambda: bool(checker(task_id))

    def _handle_gate(
        self, db: Session, *, run: WorkflowRun, project: Project, node: WorkflowNodeConfig
    ) -> str:
        stage = node.review_stage or node.id
        approved = reviews.approved_review(db, project.id, stage, workflow_run_id=run.id)
        if approved is not None:
            return "approved"
        # A rejected review means "rework and review again": the gate reopens
        # with a fresh pending review instead of failing the whole run.
        review = reviews.create_review(
            db,
            project=project,
            stage=stage,
            target_type="workflow_node",
            target_id=node.id,
            workflow_run_id=run.id,
        )
        run.awaiting_stage = stage
        run.pending_review_id = review.id
        return "awaiting"

    def _checkpoint(
        self,
        db: Session,
        run: WorkflowRun,
        node: WorkflowNodeConfig,
        *,
        status: str,
        summary: str = "",
        output: dict[str, Any] | None = None,
        error: str = "",
    ) -> WorkflowCheckpoint:
        checkpoint = WorkflowCheckpoint(
            id=new_id("ckpt"),
            run_id=run.id,
            project_id=run.project_id,
            node_id=node.id,
            node_type=node.type,
            status=status,
            summary=summary[:2000],
            state={"next_index": (run.state or {}).get("next_index")},
            output=output or {},
            error=error,
        )
        db.add(checkpoint)
        db.flush()
        return checkpoint

    def _progress(self, task: Task | None, index: int, total: int, node: WorkflowNodeConfig) -> None:
        if task is None:
            return
        task.progress = round(min(0.99, index / max(1, total)), 3)
        task.stage = node.id
        task.message = f"{node.title or node.id} 完成"


def _summary(node: WorkflowNodeConfig, output: dict[str, Any]) -> str:
    title = node.title or node.id
    if not output:
        return f"{title} 完成"
    pairs = ", ".join(
        f"{key}={value}"
        for key, value in output.items()
        if isinstance(value, (str, int, float, bool)) and value != ""
    )
    return f"{title} 完成（{pairs}）" if pairs else f"{title} 完成"


# ------------------------------------------------------------------ queries
def get_run(db: Session, project_id: str, run_id: str) -> WorkflowRun:
    run = db.get(WorkflowRun, run_id)
    if run is None or run.project_id != project_id:
        raise WorkflowError("工作流实例不存在", details={"workflow_run_id": run_id})
    return run


def latest_run(db: Session, project_id: str) -> WorkflowRun | None:
    return db.scalar(
        select(WorkflowRun)
        .where(WorkflowRun.project_id == project_id)
        .order_by(WorkflowRun.created_at.desc())
    )


def list_runs(db: Session, project_id: str) -> list[WorkflowRun]:
    return list(
        db.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.project_id == project_id)
            .order_by(WorkflowRun.created_at.desc())
        )
    )


def checkpoints(db: Session, run_id: str) -> list[WorkflowCheckpoint]:
    return list(
        db.scalars(
            select(WorkflowCheckpoint)
            .where(WorkflowCheckpoint.run_id == run_id)
            .order_by(WorkflowCheckpoint.created_at)
        )
    )


def run_public(db: Session, run: WorkflowRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "project_id": run.project_id,
        "definition_id": run.definition_id,
        "definition_version": run.definition_version,
        "status": run.status,
        "current_node": run.current_node,
        "awaiting_stage": run.awaiting_stage,
        "pending_review_id": run.pending_review_id,
        "task_id": run.task_id,
        "error": run.error,
        "state": run.state or {},
        "config_versions": run.config_versions or {},
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "checkpoints": [
            {
                "id": checkpoint.id,
                "node_id": checkpoint.node_id,
                "node_type": checkpoint.node_type,
                "status": checkpoint.status,
                "summary": checkpoint.summary,
                "error": checkpoint.error,
                "created_at": checkpoint.created_at.isoformat()
                if checkpoint.created_at
                else None,
            }
            for checkpoint in checkpoints(db, run.id)
        ],
    }


def cancel(db: Session, run: WorkflowRun, reason: str = "用户取消") -> WorkflowRun:
    run.status = WorkflowStatus.CANCELLED.value
    run.error = reason
    run.finished_at = utcnow()
    db.flush()
    return run
