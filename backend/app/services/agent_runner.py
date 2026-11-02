"""Agent execution wrapper.

Every agent invocation in the platform goes through :func:`run_agent`, which is
what makes results traceable and reproducible:

* the agent config used is frozen into the ``AgentRun`` row;
* latency / tokens / cost are recorded in ``agent_runs`` and ``model_call_logs``;
* cost is added to the project budget ledger;
* provider errors are wrapped without losing the original traceback.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.base import AgentContext, AgentResult
from app.agents.registry import create_agent
from app.core.exceptions import AppError, ProviderError
from app.models.ops import AgentRun, ModelCallLog, Task
from app.models.project import BudgetEvent, Project
from app.services.runtime import AppRuntime

logger = logging.getLogger(__name__)


def json_safe(value: Any) -> Any:
    """Make arbitrary agent input/output JSON-column friendly."""
    if isinstance(value, BaseModel):
        # Python-mode dump first: JSON mode cannot encode raw bytes.
        return json_safe(value.model_dump())
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return json_safe(dataclasses.asdict(value))
    if isinstance(value, bytes):
        return {"__bytes__": len(value)}
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def serialize_output(output: Any) -> dict[str, Any]:
    if isinstance(output, BaseModel):
        return json_safe(output.model_dump())
    if dataclasses.is_dataclass(output) and not isinstance(output, type):
        payload = dataclasses.asdict(output)
        payload.pop("content", None)  # binary payloads are never copied into the DB
        return json_safe(payload)
    return {"value": json_safe(output)}


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
        evaluation = await agent.evaluate(result.output, ctx) if isinstance(result.output, BaseModel) else None
        if evaluation is not None:
            run.meta = {**(run.meta or {}), "evaluation": json_safe(evaluation)}
    except Exception:  # evaluation must never break production
        logger.debug("agent evaluation failed", exc_info=True)

    db.flush()
    return result


def dumps(value: Any) -> str:
    return json.dumps(json_safe(value), ensure_ascii=False)
