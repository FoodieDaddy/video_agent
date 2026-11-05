"""Character Image Agent.

The "Character Prompt Engine" lives here: appearance constraints (face, hair,
costume, body) are rendered from the *approved* profile into every view request so
a portrait, a turnaround sheet and a costume sheet stay consistent.  Generated
images keep their parent asset so lineage is traceable.
"""

from __future__ import annotations

from string import Template
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ai_runtime.base import AgentContext, AgentResult, MediaAgent
from app.modules.ai_runtime.providers import registry as provider_registry
from app.modules.ai_runtime.providers.base import ImageRequest

_SIZE_BY_KIND = {
    "portrait": (1024, 1024),
    "full_body": (768, 1024),
    "turnaround": (1536, 1024),
    "expression": (1024, 1024),
    "costume": (768, 1024),
    "scene_reference": (1280, 720),
}

_VIEW_BY_KIND = {
    "portrait": "正面半身定妆照，面部清晰，纯色背景",
    "full_body": "正面全身站姿，完整展示身材比例与服装",
    "turnaround": "三视图设定稿：正面、侧面、背面并列，同一角色同一服装，纯色背景",
    "expression": "同一角色的表情设定图，九宫格表情，面部特征保持一致",
    "costume": "同一角色的服装设定图，展示服装细节与材质",
}


class CharacterImageInput(BaseModel):
    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    project_id: str = ""
    character_id: str = ""
    name: str = ""
    profile: dict = Field(default_factory=dict)
    kind: str = "portrait"
    expression: str = ""
    costume: str = ""
    style_tokens: list[str] = Field(default_factory=list)
    reference_image: bytes | None = None
    label: str = ""


class CharacterImageAgent(MediaAgent):
    agent_id: ClassVar[str] = "character_image"
    capability: ClassVar[str] = "image"
    input_model: ClassVar[type] = CharacterImageInput

    def build_prompt(self, inputs: CharacterImageInput) -> tuple[str, str]:
        profile = inputs.profile or {}
        template = Template(self.config_store.prompt_text("prompts/character/image_prompt.md"))
        keywords = profile.get("visual_keywords") or []
        prompt = template.safe_substitute(
            name=inputs.name or profile.get("name", ""),
            appearance=profile.get("appearance", ""),
            hairstyle=profile.get("hairstyle", ""),
            body=profile.get("body", ""),
            clothing=profile.get("clothing_default", ""),
            costume=inputs.costume,
            expression=inputs.expression,
            keywords="、".join(str(item) for item in keywords),
            view=_VIEW_BY_KIND.get(inputs.kind, _VIEW_BY_KIND["portrait"]),
            style="、".join(inputs.style_tokens) or "电影感写实风格，柔和自然光",
        )
        negative = self.config_store.prompt_text("prompts/character/image_negative.md").strip()
        return " ".join(prompt.split()), negative

    async def execute(self, inputs: CharacterImageInput, ctx: AgentContext) -> AgentResult:
        provider = provider_registry.get_image(self.config_store, self.config.model)
        prompt, negative = self.build_prompt(inputs)
        width, height = _SIZE_BY_KIND.get(inputs.kind, (1024, 1024))
        request = ImageRequest(
            prompt=prompt,
            negative_prompt=negative,
            width=width,
            height=height,
            count=1,
            model_id=self.config.model.model_id,
            reference_images=[inputs.reference_image] if inputs.reference_image else [],
            meta={"kind": inputs.kind, "label": inputs.label or f"{inputs.name}_{inputs.kind}"},
        )
        result = await provider.generate(request)
        return AgentResult(
            output=result,
            provider=result.provider,
            model_id=result.model_id,
            prompt_version=self.config_store.prompt_version(
                "prompts/character/image_prompt.md", "prompts/character/image_negative.md"
            ),
            config_version=self.config.config_version,
            cost_usd=result.cost_usd,
            attempts=1,
            meta={
                "prompt": prompt,
                "negative_prompt": negative,
                "kind": inputs.kind,
                "width": result.width,
                "height": result.height,
            },
        )
