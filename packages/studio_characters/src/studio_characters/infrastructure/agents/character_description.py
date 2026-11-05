"""Character Description Agent: canonical, fact/inference separated profile."""

from __future__ import annotations

from typing import Any, ClassVar

from studio_ai_runtime.base import AgentContext, StructuredLLMAgent
from studio_characters.contracts import CharacterDescriptionInput, CharacterProfileOutput


class CharacterDescriptionAgent(StructuredLLMAgent):
    agent_id: ClassVar[str] = "character_description"
    input_model: ClassVar[type] = CharacterDescriptionInput
    output_model: ClassVar[type] = CharacterProfileOutput
    schema_name: ClassVar[str] = "character_profile"

    def build_variables(self, inputs: CharacterDescriptionInput, ctx: AgentContext) -> dict[str, Any]:
        evidence = inputs.evidence or []
        return {
            "name": inputs.name,
            "evidence": evidence,
            "evidence_text": "\n".join(evidence),
            "chapter_texts": inputs.chapter_texts,
            "script": inputs.script,
            "language": inputs.language,
        }

    def postprocess(
        self, output: CharacterProfileOutput, inputs: CharacterDescriptionInput, ctx: AgentContext
    ) -> CharacterProfileOutput:
        # 人物身份由调用方选定，描述模型不能通过另一个输出名字更换档案归属。
        output.name = inputs.name or output.name
        output.visual_keywords = [item for item in output.visual_keywords if item][:12]
        # source_facts 只做前 12 字片段匹配与证据回填的启发式过滤；输入证据为空时
        # 原事实列表仍可保留，因此这里不是完整事实核查或无幻觉保证。
        evidence_blob = "\n".join(inputs.evidence or [])
        output.source_facts = [
            fact for fact in output.source_facts if not evidence_blob or fact[:12] in evidence_blob
        ] or (inputs.evidence or [])[:4]
        if output.gender not in {"male", "female", "unknown"}:
            output.gender = "unknown"
        return output
