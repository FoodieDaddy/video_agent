"""技术运行记录的只读值类型。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TaskReference:
    """任务身份及当前状态；不携带会话、结果 JSON 或可变 ORM 行。"""

    id: str
    project_id: str
    status: str
