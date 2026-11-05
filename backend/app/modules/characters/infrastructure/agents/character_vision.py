"""Character Vision Agent: analyse user uploaded reference images."""

from __future__ import annotations

from typing import Any, ClassVar

from app.modules.ai_runtime.base import AgentContext, AgentResult, StructuredVisionAgent
from app.modules.characters.contracts import CharacterVisionInput, CharacterVisionOutput


class CharacterVisionAgent(StructuredVisionAgent):
    agent_id: ClassVar[str] = "character_vision"
    capability: ClassVar[str] = "vision"
    input_model: ClassVar[type] = CharacterVisionInput
    output_model: ClassVar[type] = CharacterVisionOutput
    schema_name: ClassVar[str] = "character_vision"

    def build_variables(self, inputs: CharacterVisionInput, ctx: AgentContext) -> dict[str, Any]:
        # Image bytes are sent through the vision channel, never in prompt text.
        return {
            "filename": inputs.filename,
            "known_name": inputs.known_name,
            "known_description": inputs.known_description,
        }

    async def execute(self, inputs: CharacterVisionInput, ctx: AgentContext) -> AgentResult:
        if not inputs.image_bytes:
            raise ValueError("CharacterVisionAgent requires image bytes")
        return await self.invoke(
            variables=self.build_variables(inputs, ctx),
            ctx=ctx,
            schema_name=self.schema_name,
            output_model=self.output_model,
            inputs=inputs,
            image_bytes=inputs.image_bytes,
            image_mime=inputs.image_mime,
        )
