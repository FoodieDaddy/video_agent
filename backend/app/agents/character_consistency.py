"""Character Consistency Agent: compares approved reference images with new assets."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from app.agents.base import AgentContext, AgentResult, StructuredVisionAgent
from app.schemas.character import CharacterConsistencyOutput, ConsistencyIssue


class ConsistencyInput(BaseModel):
    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    character_id: str = ""
    name: str = ""
    profile_summary: str = ""
    asset_kinds: list[str] = Field(default_factory=list)
    checked_assets: int = 0
    reference_image: bytes | None = None
    image_mime: str = "image/png"


class CharacterConsistencyAgent(StructuredVisionAgent):
    agent_id: ClassVar[str] = "character_consistency"
    capability: ClassVar[str] = "vision"
    input_model: ClassVar[type] = ConsistencyInput
    output_model: ClassVar[type] = CharacterConsistencyOutput
    schema_name: ClassVar[str] = "character_consistency"

    def build_variables(self, inputs: ConsistencyInput, ctx: AgentContext) -> dict[str, Any]:
        return {
            "character_id": inputs.character_id,
            "name": inputs.name,
            "profile_summary": inputs.profile_summary,
            "asset_kinds": inputs.asset_kinds,
            "checked_assets": inputs.checked_assets,
        }

    async def execute(self, inputs: ConsistencyInput, ctx: AgentContext) -> AgentResult:
        if not inputs.reference_image:
            output = CharacterConsistencyOutput(
                character_id=inputs.character_id,
                overall_score=0.65 if not inputs.checked_assets else 0.8,
                checked_assets=inputs.checked_assets,
                issues=[
                    ConsistencyIssue(
                        type="missing_assets",
                        severity="medium",
                        description="缺少可用于比对的角色形象资产",
                    )
                ],
                recommendation="regenerate",
            )
            return AgentResult(
                output=output,
                provider="local-rule",
                model_id="rule:no-reference",
                config_version=self.config.config_version,
                meta={"skipped_vision": True},
            )
        return await self.invoke(
            variables=self.build_variables(inputs, ctx),
            ctx=ctx,
            schema_name=self.schema_name,
            output_model=self.output_model,
            inputs=inputs,
            image_bytes=inputs.reference_image,
            image_mime=inputs.image_mime,
        )
