"""story 模块的公开数据契约；重新导出现有类型，保持 Schema 单一来源。"""

from dataclasses import dataclass

from app.schemas.script import ChapterSummary, DialogueLine, ScriptInput, ScriptOutput, StoryEventDraft


@dataclass(frozen=True, slots=True)
class ScriptBaselineReference:
    """审核或恢复流程确认过的剧本基线，不携带 SQLAlchemy 实体。"""

    project_id: str
    script_id: str
    version: int
    fingerprint: str


__all__ = [
    "ChapterSummary",
    "DialogueLine",
    "ScriptBaselineReference",
    "ScriptInput",
    "ScriptOutput",
    "StoryEventDraft",
]
