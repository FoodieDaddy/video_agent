"""Character Description Agent: canonical, fact/inference separated profile."""

from __future__ import annotations

from typing import Any, ClassVar

from app.agents.base import AgentContext, StructuredLLMAgent
from app.schemas.character import CharacterDescriptionInput, CharacterProfileOutput


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
        output.name = inputs.name or output.name
        output.visual_keywords = [item for item in output.visual_keywords if item][:12]
        # Facts must be traceable to the source evidence, never invented.
        evidence_blob = "\n".join(inputs.evidence or [])
        output.source_facts = [
            fact for fact in output.source_facts if not evidence_blob or fact[:12] in evidence_blob
        ] or (inputs.evidence or [])[:4]
        if output.gender not in {"male", "female", "unknown"}:
            output.gender = "unknown"
        return output
