"""workflow 模块的公开数据契约；重新导出现有类型，保持 Schema 单一来源。"""

from dataclasses import dataclass

from studio_workflow.schemas.orchestrator import OrchestratorInput, OrchestratorPlan, WorkflowPlanNode


@dataclass(frozen=True, slots=True)
class WorkflowRunReference:
    """供审批后恢复条件判断读取的运行身份与状态。"""

    id: str
    project_id: str
    status: str


__all__ = [
    "OrchestratorInput",
    "OrchestratorPlan",
    "WorkflowPlanNode",
    "WorkflowRunReference",
]
