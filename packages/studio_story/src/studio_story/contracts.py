"""story 模块的公开数据契约；重新导出现有类型，保持 Schema 单一来源。"""

from dataclasses import dataclass
from typing import Any

from studio_story.schemas.script import (
    ChapterSummary,
    DialogueLine,
    ScriptInput,
    ScriptOutput,
    StoryEventDraft,
)


@dataclass(frozen=True, slots=True)
class ScriptBaselineReference:
    """审核或恢复流程确认过的剧本基线，不携带 SQLAlchemy 实体。"""

    project_id: str
    script_id: str
    version: int
    fingerprint: str


@dataclass(frozen=True, slots=True)
class ScriptSnapshot:
    """一次读取的剧本投影；正文结构为深副本，可独立于数据库会话使用。

    冻结字段绑定而非嵌套 dict；调用方修改 content 不会修改数据库记录。
    指纹对应本次读取，后续写入前仍须显式校验基线。
    """

    id: str
    project_id: str
    version: int
    title: str
    logline: str
    synopsis: str
    genre: str
    tone: str
    content: dict[str, Any]
    script_text: str
    fingerprint: str
    approved: bool


__all__ = [
    "ChapterSummary",
    "DialogueLine",
    "ScriptBaselineReference",
    "ScriptInput",
    "ScriptOutput",
    "ScriptSnapshot",
    "StoryEventDraft",
]
