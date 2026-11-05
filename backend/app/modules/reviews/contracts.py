"""审核协调所需的只读端口与 DTO；不依赖工作流 ORM。"""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class WorkflowScriptBaseline:
    script_id: str
    fingerprint: str | None


@dataclass(frozen=True, slots=True)
class WorkflowReviewReference:
    project_id: str
    script_baselines: tuple[WorkflowScriptBaseline, ...]


class WorkflowReviewReader(Protocol):
    """在调用方事务内查询审核关联运行，存在时返回项目与剧本基线。"""

    def __call__(self, db: Any, run_id: str, project_id: str) -> WorkflowReviewReference | None: ...


__all__ = ["WorkflowReviewReader", "WorkflowReviewReference", "WorkflowScriptBaseline"]
