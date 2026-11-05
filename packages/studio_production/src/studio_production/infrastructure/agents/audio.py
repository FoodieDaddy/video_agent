"""Audio Agent: voice line planning plus TTS synthesis.

Two agent ids are involved:

* ``audio``       — structured planning of narration / dialogue / music cues;
* ``audio_voice`` — text-to-speech through the configured audio provider.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from studio_ai_runtime.base import AgentContext, AgentResult, MediaAgent, StructuredLLMAgent
from studio_ai_runtime.providers import registry as provider_registry
from studio_ai_runtime.providers.base import AudioRequest
from studio_production.contracts import AudioPlanInput, AudioPlanOutput


class AudioAgent(StructuredLLMAgent):
    agent_id: ClassVar[str] = "audio"
    input_model: ClassVar[type] = AudioPlanInput
    output_model: ClassVar[type] = AudioPlanOutput
    schema_name: ClassVar[str] = "audio_plan"

    def build_variables(self, inputs: AudioPlanInput, ctx: AgentContext) -> dict[str, Any]:
        return {
            "shots": inputs.shots,
            "synopsis": inputs.synopsis,
            "language": inputs.language,
            "style": inputs.style,
            "shot_count": len(inputs.shots),
        }

    def postprocess(
        self, output: AudioPlanOutput, inputs: AudioPlanInput, ctx: AgentContext
    ) -> AudioPlanOutput:
        seen: set[str] = set()
        lines = []
        for index, line in enumerate(output.voice_lines, start=1):
            text = (line.text or "").strip()
            if not text:
                continue
            line.line_id = line.line_id or f"line_{index:03d}"
            if line.line_id in seen:
                line.line_id = f"{line.line_id}_{index}"
            seen.add(line.line_id)
            if not line.duration_seconds or line.duration_seconds <= 0:
                line.duration_seconds = round(max(1.0, len(text) / 4.5), 2)
            lines.append(line)
        output.voice_lines = lines
        if not output.music_cue:
            output.music_cue = "低沉弦乐铺底，音量低于人声" if lines else "轻柔环境音"
        return output


class VoiceSynthesisInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    line_id: str = ""
    text: str
    character_name: str = ""
    emotion: str = ""
    voice: str = ""
    style: str = ""
    language: str = "zh"
    speed: float = 1.0
    audio_format: str = "wav"


class AudioVoiceAgent(MediaAgent):
    agent_id: ClassVar[str] = "audio_voice"
    capability: ClassVar[str] = "audio"
    input_model: ClassVar[type] = VoiceSynthesisInput

    async def execute(self, inputs: VoiceSynthesisInput, ctx: AgentContext) -> AgentResult:
        provider = provider_registry.get_audio(self.config_store, self.config.model)
        started = time.perf_counter()
        options = dict(self.config.model.provider_options or {})
        request = AudioRequest(
            text=inputs.text,
            voice=inputs.voice or str(options.get("voice") or "alloy"),
            style=inputs.style or inputs.emotion,
            language=inputs.language,
            speed=inputs.speed,
            audio_format=inputs.audio_format,
            model_id=self.config.model.model_id,
            meta={"line_id": inputs.line_id, "character_name": inputs.character_name},
        )
        result = await provider.synthesize(request)
        return AgentResult(
            output=result,
            provider=result.provider or provider.name,
            model_id=result.model_id or self.config.model.model_id,
            config_version=self.config.config_version,
            latency_ms=(time.perf_counter() - started) * 1000,
            cost_usd=result.cost_usd,
            attempts=1,
            meta={
                "line_id": inputs.line_id,
                "duration_seconds": result.duration_seconds,
                "provider_meta": result.meta,
            },
        )
