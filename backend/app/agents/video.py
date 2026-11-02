"""Video Agent: calls the configured video provider for a single shot.

The agent is provider agnostic — it only knows the ``VideoProvider`` interface.
Synchronously returning providers and asynchronous submit/poll providers are
both supported by the interface, so a new vendor never changes agent code.
"""

from __future__ import annotations

import time
from typing import ClassVar

from app.agents.base import AgentContext, AgentResult, MediaAgent
from app.providers import registry as provider_registry
from app.providers.base import VideoRequest
from app.schemas.video import ShotVideoInput


class VideoAgent(MediaAgent):
    agent_id: ClassVar[str] = "video"
    capability: ClassVar[str] = "video"
    input_model: ClassVar[type] = ShotVideoInput

    async def execute(self, inputs: ShotVideoInput, ctx: AgentContext) -> AgentResult:
        provider = provider_registry.get_video(self.config_store, self.config.model)
        started = time.perf_counter()
        request = VideoRequest(
            prompt=inputs.prompt,
            negative_prompt=inputs.negative_prompt,
            duration_seconds=inputs.duration_seconds,
            aspect_ratio=inputs.aspect_ratio,
            width=inputs.width,
            height=inputs.height,
            model_id=self.config.model.model_id,
            reference_image=inputs.reference_image,
            first_frame=inputs.first_frame,
            last_frame=inputs.last_frame,
            provider_options={**self.config.model.provider_options, **inputs.provider_options},
            meta={"shot_id": inputs.shot_id, **inputs.extra},
        )
        result = await provider.generate(request)
        return AgentResult(
            output=result,
            provider=result.provider or provider.name,
            model_id=result.model_id or self.config.model.model_id,
            config_version=self.config.config_version,
            latency_ms=(time.perf_counter() - started) * 1000,
            cost_usd=result.cost_usd,
            attempts=1,
            meta={
                "shot_id": inputs.shot_id,
                "task_ref": result.task_ref,
                "placeholder": bool(result.meta.get("placeholder")),
                "provider_meta": result.meta,
            },
        )

    async def cancel(self, task_ref: str) -> bool:
        provider = provider_registry.get_video(self.config_store, self.config.model)
        return await provider.cancel(task_ref)
