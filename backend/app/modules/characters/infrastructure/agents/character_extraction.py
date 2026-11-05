"""Character Extraction Agent: find characters and relationships in the script."""

from __future__ import annotations

from typing import Any, ClassVar

from app.modules.ai_runtime.base import AgentContext, StructuredLLMAgent
from app.modules.characters.contracts import (
    CharacterCandidate,
    CharacterExtractionInput,
    CharacterExtractionOutput,
)
from app.modules.platform.text import narrative


class CharacterExtractionAgent(StructuredLLMAgent):
    agent_id: ClassVar[str] = "character_extraction"
    input_model: ClassVar[type] = CharacterExtractionInput
    output_model: ClassVar[type] = CharacterExtractionOutput
    schema_name: ClassVar[str] = "character_extraction"

    def build_variables(self, inputs: CharacterExtractionInput, ctx: AgentContext) -> dict[str, Any]:
        chapters = inputs.chapter_texts or []
        joined = "\n\n".join(f"【{item.get('title', '')}】\n{item.get('content', '')}" for item in chapters)
        return {
            "chapter_texts": chapters,
            "script": inputs.script,
            "language": inputs.language,
            "source_excerpt": joined[:20000],
        }

    def postprocess(
        self, output: CharacterExtractionOutput, inputs: CharacterExtractionInput, ctx: AgentContext
    ) -> CharacterExtractionOutput:
        # 空列表符合提取输出的 Schema，因此在业务后处理里补候选；这些候选来自
        # 本地文本规则或“主角”占位，不能把非空结果都算成模型成功识别人名。
        seen: set[str] = set()
        unique = []
        for candidate in output.characters:
            name = (candidate.name or "").strip()
            if not name or name in seen or name == "未知":
                continue
            seen.add(name)
            unique.append(candidate)
        if not unique:
            chapter_text = "\n".join(str(item.get("content", "")) for item in inputs.chapter_texts)
            for name in narrative.extract_character_names(chapter_text, limit=3) or ["主角"]:
                if name in seen:
                    continue
                seen.add(name)
                unique.append(
                    CharacterCandidate(
                        name=name,
                        role_hint="protagonist" if not unique else "supporting",
                        evidence=f"{name} 在原文中反复出现",
                    )
                )
        output.characters = unique
        # 这里只筛本次候选名称范围；持久化服务再将关系端点映射为同项目人物 ID。
        output.relationships = [
            relation
            for relation in output.relationships
            if relation.source in seen and relation.target in seen
        ]
        return output
