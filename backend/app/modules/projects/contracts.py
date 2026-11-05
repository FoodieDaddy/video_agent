"""项目模块向其他模块提供的脱离 Session 的上下文。"""

from dataclasses import dataclass
from typing import Any


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


__all__ = ["ProjectContext"]
