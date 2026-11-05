"""按 YAML 节点顺序执行、在节点边界记录游标的工作流引擎。

handler、人工审核和失败处理会更新 WorkflowRun 与 checkpoint，并由引擎在
对应节点边界提交调用方 Session。审核暂停后可从保存的 next_index 继续。
这不提供任意崩溃下的恰好一次执行：外部副作用与节点提交之间仍需幂等、
对账和取消协调；恢复默认读取当前定义，不等同于冻结的完整工作流快照。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from studio_platform.configuration.config_models import WorkflowConfig, WorkflowNodeConfig
from studio_platform.constants import WorkflowStatus
from studio_platform.exceptions import ValidationAppError, WorkflowError
from studio_platform.execution.runtime import AppRuntime
from studio_platform.ids import new_id, utcnow
from studio_platform.persistence.models import Task
from studio_projects.contracts import ProjectContext as Project
from studio_reviews import public as reviews
from studio_workflow.application.handlers import HandlerContext, build_handlers, require_handler
from studio_workflow.infrastructure.persistence.models import WorkflowCheckpoint, WorkflowRun

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """协调生产阶段与审核关卡，不承担独立线程调度或远端作业生命周期。

    调用方负责项目鉴权及 Session 生命周期。引擎持有当前 runtime，handlers
    可在受控测试中替换；执行中会提交传入 Session，调用前不能混入无关待提交写入。
    """

    def __init__(self, runtime: AppRuntime) -> None:
        self.runtime = runtime
        self.handlers = build_handlers()

    # ------------------------------------------------------------- 生命周期
    async def start(
        self,
        db: Session,
        *,
        project: Project,
        workflow_id: str | None = None,
        task: Task | None = None,
        user_id: str = "",
    ) -> WorkflowRun:
        """创建工作流实例，并顺序执行到待审、完成或失败边界。

        Args:
            db: 调用方拥有的同步 Session。
            project: 当前会话中已经授权的项目。
            workflow_id: 为空时采用当前配置的默认定义。
            task: 可选任务，应来自当前会话与同一业务范围。
            user_id: 仅作为执行归属，本入口不重新鉴权。

        Returns:
            同一个 WorkflowRun ORM 对象，可能处于 awaiting_review 或 completed。

        Raises:
            WorkflowError: 定义没有节点。
            ValidationAppError: 查询到相同项目与定义的活动实例。
            其他异常: 配置与节点异常按 run 的语义传播。

        Notes:
            新增实例后调用 run，后者会在节点边界 commit 传入 Session。
            活动实例检查是查询后插入，不是并发锁；版本字段仅记录身份，
            不保存完整定义快照。
        """
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
                # Freeze the executable definition at creation time. Resuming a run
                # must not silently switch node order/handlers after a YAML edit.
                "workflow_definition": workflow.model_dump(mode="json", exclude={"source_path"}),
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
        """从保存的 next_index 恢复 awaiting_review、failed 或 pending 实例。

        Args:
            db: 调用方拥有的同步 Session。
            run: 待恢复的实例，须与 project 属于同一已授权项目。
            project: 当前会话中已经授权的项目。
            task: 提供时替换实例的任务归属。
            user_id: 传给后续节点的执行用户标识，不在本入口重新鉴权。

        Returns:
            继续执行后的同一个 WorkflowRun，可能再次等待审核或完成。

        Raises:
            WorkflowError: 实例状态不允许恢复。
            其他异常: 配置与节点异常按 run 的语义传播。

        Notes:
            先更新运行状态及任务归属并 flush，再调用 run，并沿用其提交行为。
            未决定的 gate 会继续等待；驳回后的显式恢复重新提审，不自动重跑前序生成。
            沿用当前 runtime 定义，不保证定义变化时仍对应原节点。
        """
        if run.status not in {
            WorkflowStatus.AWAITING_REVIEW.value,
            WorkflowStatus.FAILED.value,
            WorkflowStatus.PENDING.value,
        }:
            raise WorkflowError(
                f"工作流当前状态为 {run.status}，无法恢复",
                details={"workflow_run_id": run.id},
            )
        # 已完成节点依赖记录时的剧本身份与内容；同一 ID 的旧 PATCH 也必须校验。
        # 没有 script 输出的子流程兼容跳过；旧完整流程缺指纹时明确要求重新开始。
        from studio_story import public as story

        outputs = (run.state or {}).get("outputs") or {}
        for output in outputs.values():
            if isinstance(output, dict) and output.get("script_id"):
                story.assert_script_baseline_reference(
                    db, project.id, output["script_id"], output.get("script_fingerprint")
                )
        run.status = WorkflowStatus.RUNNING.value
        run.error = ""
        run.task_id = task.id if task else run.task_id
        db.flush()

        # Prefer the immutable snapshot captured when the run was created.
        # Legacy runs without a snapshot retain the previous current-config behavior.
        snapshot = (run.state or {}).get("workflow_definition")
        workflow = WorkflowConfig.model_validate(snapshot) if isinstance(snapshot, dict) else None
        return await self.run(db, run=run, project=project, task=task, user_id=user_id, workflow=workflow)

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
        """按给定定义或当前配置，从实例游标执行节点。

        Args:
            db: 调用方拥有的同步 Session，节点边界会提交其中全部待提交写入。
            run: 当前工作流实例，应与 project 属于同一已授权项目。
            project: 当前会话中已经授权的项目。
            task: 可选任务，用于节点上下文和取消检查回调。
            user_id: 传给节点的执行用户标识，不在本入口重新鉴权。
            workflow: 提供时使用该定义，否则从 runtime 当前配置读取。

        Returns:
            同一 WorkflowRun。遇到待审时提前返回，所有配置节点推进完后为 completed；
            其中可能包含 continue_on_error 允许跳过的失败，不代表全部资产质量达标。

        Raises:
            其他异常: 普通 handler 异常按 continue_on_error 决定继续或尝试记录失败
                后重抛；数据库错误仍可能直接传播并要求调用方处理事务。

        Notes:
            节点输出写入 state.outputs，游标记录下一节点位置；每个完成、待审或失败
            边界会 commit 传入 Session。节点提交前已有外部副作用时，恢复可能重做。
            这里只把可用的任务取消检查回调放入 HandlerContext，主循环不统一确认
            任务或远端作业已经停止。引擎不提供业务锁、统一总 deadline、配置版本
            迁移或模型请求幂等保证。
        """
        workflow = workflow or self.runtime.config_store.workflow(run.definition_id)
        nodes = workflow.nodes
        # 对 JSON 状态重新赋副本，使 ORM 识别游标修改；直接复用同一 dict
        # 可能无法标脏，导致提交后恢复到旧位置。
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
                        db,
                        run,
                        node,
                        status="failed",
                        error=message[:2000],
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
                handler = require_handler(handler_name)  # 未注册时抛带名称的错误

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
                    db,
                    run,
                    node,
                    status="failed",
                    error=message[:2000],
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

    # --------------------------------------------------------------- 内部辅助
    def _stop_check(self, task: Task | None):
        """把可用的任务取消查询包装成回调；缺任务或查询能力时返回 None。

        回调是否被检查取决于 handler，不会单凭生成回调中断循环或远端请求。
        """
        checker = (self.runtime.extras or {}).get("is_cancelled")
        if task is None or not callable(checker):
            return None
        task_id = task.id
        return lambda: bool(checker(task_id))

    def _handle_gate(
        self, db: Session, *, run: WorkflowRun, project: Project, node: WorkflowNodeConfig
    ) -> str:
        """检查同项目、同工作流实例的审核结果，否则创建或复用待审记录。

        已有 approved Review 返回 approved；pending 或驳回后恢复均返回 awaiting，
        并设置 awaiting_stage/pending_review_id。审核对象版本的业务约束由审核用例处理，
        分镜快照由审核用例冻结，已批准的第二关在续跑前再次核验；其它档案仍沿用
        原语义。此处不重跑生成，也不自行提交事务。
        """
        stage = node.review_stage or node.id
        approved = reviews.approved_review(db, project.id, stage, workflow_run_id=run.id)
        if approved is not None:
            if stage == "storyboard":
                reviews.assert_review_targets(db, project=project, review=approved)
            return "approved"
        # 驳回后显式恢复会在当前关卡新建待审单；仅重新提审，不自动返工模型。
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
        """新增当前节点的检查点并 flush，保存的是 next_index 摘要而非完整快照。"""
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
        """更新关联任务的阶段和进度字段，不提交；运行中进度上限为0.99。"""
        if task is None:
            return
        task.progress = round(min(0.99, index / max(1, total)), 3)
        task.stage = node.id
        task.message = f"{node.title or node.id} 完成"


def _summary(node: WorkflowNodeConfig, output: dict[str, Any]) -> str:
    """将节点输出的标量字段拼为日志摘要，不代表产物已通过质量检查。"""
    title = node.title or node.id
    if not output:
        return f"{title} 完成"
    pairs = ", ".join(
        f"{key}={value}"
        for key, value in output.items()
        if isinstance(value, (str, int, float, bool)) and value != ""
    )
    return f"{title} 完成（{pairs}）" if pairs else f"{title} 完成"


# ------------------------------------------------------------------ 查询与状态入口
def get_run(db: Session, project_id: str, run_id: str) -> WorkflowRun:
    """按项目和运行ID读取实例；不存在或项目不匹配时抛 WorkflowError。

    只核对传入项目ID，不验证项目成员权限；调用方应先完成鉴权。
    """
    run = db.get(WorkflowRun, run_id)
    if run is None or run.project_id != project_id:
        raise WorkflowError("工作流实例不存在", details={"workflow_run_id": run_id})
    return run


def latest_run(db: Session, project_id: str) -> WorkflowRun | None:
    """查询项目最近创建的实例，可返回 None；调用方负责权限与会话。"""
    return db.scalar(
        select(WorkflowRun)
        .where(WorkflowRun.project_id == project_id)
        .order_by(WorkflowRun.created_at.desc())
    )


def list_runs(db: Session, project_id: str) -> list[WorkflowRun]:
    """按创建时间倒序列出项目实例，不修改状态或执行任务。"""
    return list(
        db.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.project_id == project_id)
            .order_by(WorkflowRun.created_at.desc())
        )
    )


def checkpoints(db: Session, run_id: str) -> list[WorkflowCheckpoint]:
    """查询运行ID的检查点；调用方应先验证该运行所属项目的访问权限。"""
    return list(
        db.scalars(
            select(WorkflowCheckpoint)
            .where(WorkflowCheckpoint.run_id == run_id)
            .order_by(WorkflowCheckpoint.created_at)
        )
    )


def run_public(db: Session, run: WorkflowRun) -> dict[str, Any]:
    """组装运行状态、时间字符串及检查点供接口返回。

    会查询检查点，不自行鉴权或提交；state/config_versions 是已记录数据，不构成
    完整配置快照，也不独立证明某份资产已经批准。
    """
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
                "created_at": checkpoint.created_at.isoformat() if checkpoint.created_at else None,
            }
            for checkpoint in checkpoints(db, run.id)
        ],
    }


def cancel(db: Session, run: WorkflowRun, reason: str = "用户取消") -> WorkflowRun:
    """在当前事务内标记工作流取消并 flush，返回同一实例。

    更新 status/error/finished_at，但不 commit、不通知 TaskRunner、不终止当前节点
    或远端作业。调用方负责提交和取消传播，标记完成不等于执行已确认停止。
    """
    run.status = WorkflowStatus.CANCELLED.value
    run.error = reason
    run.finished_at = utcnow()
    db.flush()
    return run
