"""复用同一 script Agent 分析章节、润色现稿和生成续写片段。"""

from __future__ import annotations

from typing import Any, ClassVar

from app.modules.ai_runtime.base import AgentContext, StructuredLLMAgent
from app.modules.platform.text import narrative
from app.modules.story.contracts import ChapterSummary, ScriptInput, ScriptOutput, StoryEventDraft


class ScriptAgent(StructuredLLMAgent):
    """生成正文候选与故事结构，不保存业务版本或合并续写原稿。

    Notes:
        润色返回完整新正文；续写仅返回新增正文，应用层负责保留原稿后追加。
        这里只检查正文是否可用及续写是否重复完整原稿，不能证明语义连续性、
        事实准确或润色质量；这些仍需审核。失败沿用结构化基类的修复与报错。
    """

    agent_id: ClassVar[str] = "script"
    input_model: ClassVar[type] = ScriptInput
    output_model: ClassVar[type] = ScriptOutput
    schema_name: ClassVar[str] = "script"

    def build_variables(self, inputs: ScriptInput, ctx: AgentContext) -> dict[str, Any]:
        """渲染操作、要求和完整现稿；现稿不使用章节节选的长度裁切。"""
        chapters = inputs.chapters or []
        joined = "\n\n".join(f"【{item.get('title', '')}】\n{item.get('content', '')}" for item in chapters)
        return {
            "operation": inputs.operation,
            "chapters": chapters,
            "script_text": inputs.script_text,
            "current_script": inputs.current_script,
            "instruction": inputs.instruction,
            "chapter_count": len(chapters),
            "title_hint": inputs.title_hint,
            "genre": inputs.genre,
            "language": inputs.language,
            "source_excerpt": joined[:20000],
        }

    def postprocess(self, output: ScriptOutput, inputs: ScriptInput, ctx: AgentContext) -> ScriptOutput:
        """保留分析兜底，并把不可用的编辑结果交给既有结构修复流程。

        Raises:
            ValueError: 润色/续写缺正文，或续写重复回显完整原稿。

        Notes:
            strip 只用于判断，不改写模型候选或输入正文。不会把原稿/章节填回
            空的编辑结果，也不会静默移除重复原文；应用层只拼接已通过的续写片段。
            旧分析输出缺 script_text 时，从有效结构渲染可编辑草稿；不会直接复制
            原文章节充当已改编稿。章节与事件兜底只在 analyze 下运行。
        """
        if inputs.operation != "analyze":
            candidate = output.script_text.strip()
            if not candidate:
                raise ValueError("润色或续写必须返回非空的 script_text 正文，不能只返回摘要")
            if inputs.operation == "continue" and candidate.startswith(inputs.script_text.strip()):
                raise ValueError("续写 script_text 只能返回新增正文，不得回显或以完整原稿开头")

        # 兼容既有小说分析：缺章节/事件时从来源章节补结构，不伪造编辑后的正文。
        if inputs.operation == "analyze" and not output.chapters:
            output.chapters = [
                ChapterSummary(
                    index=index,
                    title=str(chapter.get("title") or f"第{index}章"),
                    summary=narrative.summarize(str(chapter.get("content", "")), 160),
                )
                for index, chapter in enumerate(inputs.chapters, start=1)
            ]
        if inputs.operation == "analyze" and not output.events:
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
        if inputs.operation == "analyze" and not output.script_text.strip():
            output.script_text = self._render_structured_draft(output)
        return output

    @staticmethod
    def _render_structured_draft(output: ScriptOutput) -> str:
        """将旧分析结果渲染为可编辑的结构化草稿，不调用模型或读取原文章节。

        Notes:
            这是兼容旧模型/离线分析结果的确定性表示，不是额外生成的完整拍摄稿。
            至少有一条非空章节摘要、事件描述或台词才生成正文，只有标题不会补文。
        """
        sections: list[str] = []
        for chapter in output.chapters:
            if chapter.summary.strip():
                sections.append(f"【第{chapter.index}章 {chapter.title}】\n{chapter.summary}")
        for index, event in enumerate(output.events, start=1):
            if event.description.strip():
                location = f"地点：{event.location}\n" if event.location else ""
                sections.append(f"【事件{index} {event.title}】\n{location}动作：{event.description}")
        lines = [
            f"{line.character_name}{f'（{line.emotion}）' if line.emotion else ''}：{line.text}"
            for line in output.dialogues
            if line.text.strip()
        ]
        if lines:
            sections.append("【对白】\n" + "\n".join(lines))
        return f"《{output.title}》\n\n" + "\n\n".join(sections) if sections else ""
