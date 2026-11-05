"""characters 模块的公开数据契约；重新导出现有类型，保持 Schema 单一来源。"""

from dataclasses import dataclass
from typing import Any

from app.modules.characters.schemas.character import (
    CharacterCandidate,
    CharacterConsistencyOutput,
    CharacterDescriptionInput,
    CharacterExtractionInput,
    CharacterExtractionOutput,
    CharacterProfileOutput,
    CharacterVisionInput,
    CharacterVisionOutput,
    ConsistencyIssue,
    RelationshipDraft,
)


@dataclass(frozen=True, slots=True)
class CharacterReference:
    """项目内的人物身份引用，不暴露档案或可变 ORM 对象。"""

    id: str
    project_id: str


@dataclass(frozen=True, slots=True)
class CharacterSnapshot:
    """供制作读取的人物身份与生成输入；payload 为脱离 ORM 的深副本。"""

    id: str
    project_id: str
    name: str
    generation_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CharacterVoiceReference:
    """语音合成需要的人物声线设置，不携带可变 ORM 对象。"""

    voice_id: str


@dataclass(frozen=True, slots=True)
class CharacterMetrics:
    """当前人物记录、档案与形象数量；不代表视觉质量或审批快照。"""

    characters: int
    profiles: int
    assets: int


__all__ = [
    "CharacterCandidate",
    "CharacterConsistencyOutput",
    "CharacterDescriptionInput",
    "CharacterExtractionInput",
    "CharacterExtractionOutput",
    "CharacterProfileOutput",
    "CharacterVisionInput",
    "CharacterVisionOutput",
    "CharacterVoiceReference",
    "CharacterMetrics",
    "CharacterReference",
    "CharacterSnapshot",
    "ConsistencyIssue",
    "RelationshipDraft",
]
