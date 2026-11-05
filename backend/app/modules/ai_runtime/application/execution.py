"""应用侧 Agent 执行协调。

记录经过校验的输入、配置指纹、结果和可取得的用量，并更新预算账本。
本模块不保存完整配置快照，不包装或吞掉执行异常，也不自行提交事务。
失败审计与业务结果共用调用方 Session，外层回滚会影响其持久化结果。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.ops import Task
from app.models.project import Project
from app.modules.ai_runtime.base import AgentContext, AgentResult
from app.modules.ai_runtime.infrastructure.persistence.models import AgentRun, BudgetEvent, ModelCallLog
from app.modules.ai_runtime.registry import create_agent
from app.modules.contracts.public import dumps, json_safe, serialize_output
from app.modules.platform.exceptions import AppError, ProviderError
from app.modules.platform.execution.runtime import AppRuntime

__all__ = ["dumps", "json_safe", "run_agent", "serialize_output"]

logger = logging.getLogger(__name__)


async def run_agent(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    agent_id: str,
    payload: dict[str, Any] | BaseModel,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
    extra: dict[str, Any] | None = None,
) -> AgentResult:
    """执行一次 Agent 业务调用，并在调用方事务中写入审计与预算。

    Args:
        db: 调用方拥有的同步 Session。
        runtime: 本次使用的配置与运行资源。
        project: 当前会话中已经授权的项目。
        agent_id: 已注册的执行 ID。
        payload: 字典或 BaseModel，输入校验先于 AgentRun 创建。
        task: 可选任务，应属于当前会话与同一业务范围。
        workflow_run_id: 调用方已经鉴权的工作流归属标识。
        user_id: 调用方已经鉴权的执行用户标识。
        extra: 由具体用例约定的附加数据。

    Returns:
        AgentResult 候选结果，不是持久化的 AgentRun 或最终审核结论。

    Raises:
        其他异常: 配置和输入校验错误直接传播；agent.execute 抛普通异常时先将
            运行标失败并 flush，然后原样重抛。协程取消不在这个普通异常分支内。
            启发式评估失败仅记 debug 日志，不撤销已经取得的候选结果。

    Notes:
        本入口不再次执行项目成员权限检查。在模型等待前新增并 flush AgentRun，
        成功后写结果、ModelCallLog、可选 BudgetEvent 及 project.spent_usd；
        不 commit、不 rollback、不另开 Session。
        模型执行可能跨越长时间网络等待并产生外部费用；本入口不提供原子外部
        调用、失败记录独立提交、幂等、总 deadline 或远端任务取消保证。
        config_version/prompt_version 是出处指纹；单条 ModelCallLog 为成功调用的
        汇总，不保证每次失败尝试都有单独日志或完整 usage。
    """
    config = runtime.config_store.agent(agent_id)
    agent = create_agent(agent_id, runtime.config_store)
    ctx = AgentContext(
        project_id=project.id,
        task_id=task.id if task else "",
        workflow_run_id=workflow_run_id,
        user_id=user_id,
        config_versions={"agent": config.config_version},
        extra=extra or {},
    )
    inputs = agent.validate_input(payload)

    run = AgentRun(
        project_id=project.id,
        task_id=task.id if task else "",
        workflow_run_id=workflow_run_id,
        agent_id=agent_id,
        status="running",
        model_provider=config.model.provider,
        model_id=config.model.model_id,
        config_version=config.config_version,
        input=json_safe(inputs),
        meta={"capability": agent.capability},
    )
    db.add(run)
    db.flush()

    started = time.perf_counter()
    try:
        result = await agent.execute(inputs, ctx)
    except Exception as exc:
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"[:4000]
        run.latency_ms = round((time.perf_counter() - started) * 1000, 1)
        db.flush()
        logger.warning("agent %s failed for project %s: %s", agent_id, project.id, exc)
        if isinstance(exc, AppError):
            raise
        if isinstance(exc, ProviderError):
            raise
        raise

    latency = result.latency_ms or round((time.perf_counter() - started) * 1000, 1)
    run.status = "succeeded"
    run.model_provider = result.provider or config.model.provider
    run.model_id = result.model_id or config.model.model_id
    run.prompt_version = result.prompt_version
    run.config_version = result.config_version or config.config_version
    run.output = serialize_output(result.output)
    run.latency_ms = latency
    run.cost_usd = float(result.cost_usd)
    run.tokens_in = result.tokens_in
    run.tokens_out = result.tokens_out
    run.attempts = result.attempts
    run.meta = {**(run.meta or {}), **json_safe(result.meta)}

    db.add(
        ModelCallLog(
            project_id=project.id,
            agent_run_id=run.id,
            provider=run.model_provider,
            capability=agent.capability,
            model_id=run.model_id,
            request_id=str((result.meta or {}).get("request_id") or ""),
            status="succeeded",
            latency_ms=latency,
            cost_usd=run.cost_usd,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            request_meta=json_safe(result.meta),
        )
    )
    if run.cost_usd:
        db.add(
            BudgetEvent(
                project_id=project.id,
                task_id=task.id if task else None,
                category=agent.capability,
                amount_usd=run.cost_usd,
                meta={"agent_id": agent_id, "model_id": run.model_id},
            )
        )
        project.spent_usd = round((project.spent_usd or 0.0) + run.cost_usd, 6)

    try:
        evaluation = (
            await agent.evaluate(result.output, ctx) if isinstance(result.output, BaseModel) else None
        )
        if evaluation is not None:
            run.meta = {**(run.meta or {}), "evaluation": json_safe(evaluation)}
    except Exception:  # 启发式评估失败只记日志，不改变已取得的执行结果
        logger.debug("agent evaluation failed", exc_info=True)

    db.flush()
    return result
