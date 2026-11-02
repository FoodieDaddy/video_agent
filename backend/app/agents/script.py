"""Script Agent: novel chapters -> structured script (events, dialogues, synopsis)."""

from __future__ import annotations

from typing import Any, ClassVar

from app.agents.base import AgentContext, StructuredLLMAgent
from app.schemas.script import ChapterSummary, ScriptInput, ScriptOutput, StoryEventDraft
from app.utils import narrative


class ScriptAgent(StructuredLLMAgent):
    agent_id: ClassVar[str] = "script"
    input_model: ClassVar[type] = ScriptInput
    output_model: ClassVar[type] = ScriptOutput
    schema_name: ClassVar[str] = "script"

    def build_variables(self, inputs: ScriptInput, ctx: AgentContext) -> dict[str, Any]:
        chapters = inputs.chapters or []
        joined = "\n\n".join(f"【{item.get('title', '')}】\n{item.get('content', '')}" for item in chapters)
        return {
            "chapters": chapters,
            "chapter_count": len(chapters),
            "title_hint": inputs.title_hint,
            "genre": inputs.genre,
            "language": inputs.language,
            "source_excerpt": joined[:20000],
        }

    def postprocess(self, output: ScriptOutput, inputs: ScriptInput, ctx: AgentContext) -> ScriptOutput:
        # Guarantee downstream agents get at least one event and one chapter summary.
        if not output.chapters:
            output.chapters = [
                ChapterSummary(
                    index=index,
                    title=str(chapter.get("title") or f"第{index}章"),
                    summary=narrative.summarize(str(chapter.get("content", "")), 160),
                )
                for index, chapter in enumerate(inputs.chapters, start=1)
            ]
        if not output.events:
            output.events = [
                StoryEventDraft(
                    title=chapter.title,
                    description=chapter.summary or "（内容较少）",
                    chapter_index=chapter.index,
                    characters=[],
                    location="",
                    importance=0.5,
                )
                for chapter in output.chapters
            ]
        for event in output.events:
            event.importance = max(0.0, min(1.0, float(event.importance)))
        return output
