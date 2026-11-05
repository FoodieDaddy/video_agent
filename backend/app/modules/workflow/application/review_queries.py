"""工作流为审核提供的只读投影；不向审核模块暴露运行实体。"""

from sqlalchemy.orm import Session

from app.modules.reviews.contracts import WorkflowReviewReference, WorkflowScriptBaseline
from app.modules.workflow.infrastructure.persistence.models import WorkflowRun


def workflow_review_reference(db: Session, run_id: str, project_id: str) -> WorkflowReviewReference | None:
    """按原读取顺序投影运行基线，不刷新、不修改或提交调用方事务。"""
    run = db.get(WorkflowRun, run_id)
    if run is None:
        return None
    if run.project_id != project_id:
        # 原路径先拒绝项目不匹配，不能因另一项目的异常 state 改变错误优先级。
        return WorkflowReviewReference(project_id=run.project_id, script_baselines=())
    baselines = tuple(
        WorkflowScriptBaseline(script_id=output["script_id"], fingerprint=output.get("script_fingerprint"))
        for output in ((run.state or {}).get("outputs") or {}).values()
        if isinstance(output, dict) and output.get("script_id")
    )
    return WorkflowReviewReference(project_id=run.project_id, script_baselines=baselines)
