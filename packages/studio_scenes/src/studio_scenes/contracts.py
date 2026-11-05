"""scenes 模块的公开数据契约；重新导出现有类型，保持 Schema 单一来源。"""

from dataclasses import dataclass
from typing import Any

from studio_scenes.schemas.scene import (
    SceneCandidate,
    SceneDescriptionInput,
    SceneExtractionInput,
    SceneExtractionOutput,
    SceneProfileOutput,
)


@dataclass(frozen=True, slots=True)
class SceneSnapshot:
    """供制作读取的场景身份与生成配置；payload 为脱离 ORM 的深副本。"""

    id: str
    project_id: str
    name: str
    generation_payload: dict[str, Any]


__all__ = [
    "SceneCandidate",
    "SceneDescriptionInput",
    "SceneExtractionInput",
    "SceneExtractionOutput",
    "SceneProfileOutput",
    "SceneSnapshot",
]
