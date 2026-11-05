"""旧运行记录聚合入口；各记录映射由其所属模块持有。"""

from studio_ai_runtime.infrastructure.persistence.models import AgentRun, ModelCallLog
from studio_assets.infrastructure.persistence.models import AssetVersion
from studio_platform.persistence.models import Task, TaskEvent
from studio_reviews.infrastructure.persistence.models import Review, ReviewComment
from studio_workflow.infrastructure.persistence.models import WorkflowCheckpoint, WorkflowRun

__all__ = [
    "AgentRun",
    "AssetVersion",
    "ModelCallLog",
    "Review",
    "ReviewComment",
    "Task",
    "TaskEvent",
    "WorkflowCheckpoint",
    "WorkflowRun",
]
