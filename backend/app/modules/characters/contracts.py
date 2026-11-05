"""characters 模块的公开数据契约；重新导出现有类型，保持 Schema 单一来源。"""

from app.schemas.character import (
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

__all__ = [
    "CharacterCandidate",
    "CharacterConsistencyOutput",
    "CharacterDescriptionInput",
    "CharacterExtractionInput",
    "CharacterExtractionOutput",
    "CharacterProfileOutput",
    "CharacterVisionInput",
    "CharacterVisionOutput",
    "ConsistencyIssue",
    "RelationshipDraft",
]
