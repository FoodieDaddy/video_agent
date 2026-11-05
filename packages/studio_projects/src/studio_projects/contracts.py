"""项目模块向其他模块提供的脱离 Session 的上下文。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


class ProjectRecord(Protocol):
    """现存 HTTP 序列化适配所需的字段；不承诺脱离会话或允许直接写入。"""

    id: str
    name: str
    description: str
    owner_id: str
    status: str
    language: str
    genre: str
    aspect_ratio: str
    budget_limit_usd: float
    spent_usd: float
    settings: dict[str, Any]
    config_version: str
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProjectContext:
    """某次读取的项目值快照；settings 为独立副本，写操作通过项目公开用例完成。"""

    id: str
    name: str
    owner_id: str
    status: str
    language: str
    genre: str
    aspect_ratio: str
    budget_limit_usd: float
    spent_usd: float
    settings: dict[str, Any]
    config_version: str


__all__ = ["ProjectContext", "ProjectRecord"]
