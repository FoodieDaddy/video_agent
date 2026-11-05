"""剧本 Agent 的分析、润色与续写数据契约。"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChapterSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int
    title: str
    summary: str


class DialogueLine(BaseModel):
    model_config = ConfigDict(extra="ignore")

    character_name: str
    text: str
    emotion: str = ""
    chapter_index: int | None = None


class StoryEventDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    description: str
    chapter_index: int | None = None
    characters: list[str] = Field(default_factory=list)
    location: str = ""
    importance: float = 0.5


class ScriptInput(BaseModel):
    """一次剧本操作的输入，现稿正文与结构上下文分开传递。

    Notes:
        analyze 保持小说章节分析的既有调用方式。polish/continue 必须显式提供
        非空 script_text，current_script 仅为旧结构上下文，不能替代现稿正文。
        校验不裁切或改写原稿，正文拼接和版本持久化由应用层负责。
    """

    model_config = ConfigDict(extra="ignore")

    operation: Literal["analyze", "polish", "continue"] = "analyze"
    chapters: list[dict] = Field(default_factory=list)
    script_text: str = Field(default="", description="润色或续写所依据的完整现稿正文")
    current_script: dict[str, Any] = Field(
        default_factory=dict, description="现有剧本的标题、摘要等结构上下文"
    )
    instruction: str = Field(default="", description="本次润色或续写的具体要求")
    language: str = "zh"
    genre: str = ""
    title_hint: str = ""

    @model_validator(mode="after")
    def require_current_text(self) -> Self:
        """在模型调用前拒绝没有现稿的润色/续写，不从摘要猜测正文。"""
        if self.operation != "analyze" and not self.script_text.strip():
            raise ValueError("润色和续写必须提供非空的 script_text 现稿正文")
        return self


class ScriptOutput(BaseModel):
    """供应用层保存并交给下游使用的剧本候选。

    Notes:
        script_text 的含义取决于输入操作：analyze 为改编后的正文，polish 为
        完整修改后正文，continue 仅为新增段落。续写由应用层将原稿、固定分隔
        和该新增片段拼成最终完整正文，不能直接用新增片段覆盖原稿。
        结构字段描述本次操作后的完整故事。script_text 默认空字符串只用于
        兼容旧分析输出；Agent 可将有效分析结构渲染为可编辑草稿，保留已返回的
        非空模型正文。润色/续写中的空正文或重复原稿会被拒绝，不走该兼容路径。
    """

    model_config = ConfigDict(extra="ignore")

    title: str
    script_text: str = Field(default="", description="分析/润色为完整正文；续写仅为待追加的新增正文")
    logline: str = ""
    synopsis: str = ""
    genre: str = ""
    tone: str = ""
    chapters: list[ChapterSummary] = Field(default_factory=list)
    events: list[StoryEventDraft] = Field(default_factory=list)
    dialogues: list[DialogueLine] = Field(default_factory=list)
