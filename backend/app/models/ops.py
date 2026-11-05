"""旧运行记录聚合入口；各记录映射由其所属模块持有。"""

from app.modules.ai_runtime.infrastructure.persistence.models import AgentRun, ModelCallLog
from app.modules.assets.infrastructure.persistence.models import AssetVersion
from app.modules.platform.persistence.models import Task, TaskEvent
from app.modules.reviews.infrastructure.persistence.models import Review, ReviewComment
from app.modules.workflow.infrastructure.persistence.models import WorkflowCheckpoint, WorkflowRun

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
