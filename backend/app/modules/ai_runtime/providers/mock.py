"""Offline providers used for development, CI and demos.

They implement the exact same interfaces as commercial providers, so swapping
``mock`` for ``openai`` (or a local model worker) is a configuration change only.
"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import wave
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from app.modules.ai_runtime.providers import mock_generators
from app.modules.ai_runtime.providers.base import (
    AudioProvider,
    AudioRequest,
    AudioResult,
    ImageProvider,
    ImageRequest,
    ImageResult,
    LLMProvider,
    LLMRequest,
    LLMResult,
    VideoProvider,
    VideoRequest,
    VideoResult,
    VisionProvider,
    VisionRequest,
)
from app.modules.platform.media import ffmpeg
from app.modules.platform.text import narrative


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _color_from(seed: str) -> str:
    digest = _digest(seed)
    return f"0x{digest[0:2]}{digest[2:4]}{digest[4:6]}"


class MockLLMProvider(LLMProvider):
    capability = "llm"

    def __init__(self, name: str = "mock", model_id: str = "mock-text", options: dict | None = None) -> None:
        super().__init__(name=name, model_id=model_id, options=options)

    async def health(self) -> bool:
        return True

    async def generate(self, request: LLMRequest) -> LLMResult:
        schema_name = request.schema_name or ""
        try:
            structured = mock_generators.generate(schema_name, request.prompt_vars)
        except KeyError as exc:
            raise RuntimeError(
                f"Mock LLM cannot produce schema '{schema_name}'. Configure a real provider for this agent."
            ) from exc
        text = json.dumps(structured, ensure_ascii=False)
        return LLMResult(
            text=text,
            structured=structured,
            provider=self.name,
            model_id=self.model_id,
            request_id=f"mock_{_digest(text)[:16]}",
            tokens_in=len(request.system) + len(request.user),
            tokens_out=len(text),
            cost_usd=0.0,
            meta={"offline": True, "schema": schema_name},
        )


class MockVisionProvider(VisionProvider):
    capability = "vision"

    def __init__(
        self, name: str = "mock", model_id: str = "mock-vision", options: dict | None = None
    ) -> None:
        super().__init__(name=name, model_id=model_id, options=options)

    async def health(self) -> bool:
        return True

    async def describe(self, request: VisionRequest) -> LLMResult:
        width = height = 0
        mode = "RGB"
        try:
            with Image.open(io.BytesIO(request.image_bytes)) as image:
                width, height = image.size
                mode = image.mode
        except Exception:  # pragma: no cover - malformed image is handled by callers
            pass
        variables = dict(request.prompt_vars)
        variables.update({"image_width": width, "image_height": height, "image_mode": mode})
        structured = mock_generators.generate(request.schema_name or "character_vision", variables)
        text = json.dumps(structured, ensure_ascii=False)
        return LLMResult(
            text=text,
            structured=structured,
            provider=self.name,
            model_id=self.model_id,
            request_id=f"mockv_{_digest(text)[:16]}",
            tokens_in=len(request.user),
            tokens_out=len(text),
            cost_usd=0.0,
            meta={"offline": True, "image_width": width, "image_height": height},
        )


class MockImageProvider(ImageProvider):
    capability = "image"

    def __init__(self, name: str = "mock", model_id: str = "mock-image", options: dict | None = None) -> None:
        super().__init__(name=name, model_id=model_id, options=options)

    async def health(self) -> bool:
        return True

    async def generate(self, request: ImageRequest) -> ImageResult:
        width = max(64, min(int(request.width or 1024), 2048))
        height = max(64, min(int(request.height or 1024), 2048))
        digest = _digest(request.prompt)
        base = tuple(int(digest[index : index + 2], 16) for index in (0, 2, 4))
        accent = tuple(min(255, channel + 48) for channel in base)

        image = Image.new("RGB", (width, height), base)
        draw = ImageDraw.Draw(image)
        for offset in range(0, height, max(2, height // 64)):
            ratio = offset / max(1, height)
            color = tuple(int(base[i] * (1 - ratio) + accent[i] * ratio) for i in range(3))
            draw.line([(0, offset), (width, offset)], fill=color, width=max(2, height // 64))
        label = (request.meta.get("label") or request.meta.get("kind") or "mock")[:48]
        draw.rectangle([(0, height - 48), (width, height)], fill=(12, 16, 24))
        draw.text((16, height - 34), f"AI Film Studio / {label}", fill=(235, 240, 248))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return ImageResult(
            content=buffer.getvalue(),
            mime="image/png",
            width=width,
            height=height,
            provider=self.name,
            model_id=self.model_id,
            cost_usd=0.0,
            meta={"offline": True, "label": label},
        )


class MockVideoProvider(VideoProvider):
    capability = "video"

    def __init__(self, name: str = "mock", model_id: str = "mock-video", options: dict | None = None) -> None:
        super().__init__(name=name, model_id=model_id, options=options)
        self.ffmpeg_bin = (options or {}).get("ffmpeg_bin", "ffmpeg")

    async def health(self) -> bool:
        return ffmpeg.binary_available(self.ffmpeg_bin)

    async def generate(self, request: VideoRequest) -> VideoResult:
        duration = max(1.0, min(float(request.duration_seconds or 3.0), 8.0))
        width, height = int(request.width or 1280), int(request.height or 720)
        if not ffmpeg.binary_available(self.ffmpeg_bin):
            return VideoResult(
                content=None,
                duration_seconds=duration,
                provider=self.name,
                model_id=self.model_id,
                meta={
                    "offline": True,
                    "placeholder": True,
                    "reason": "ffmpeg not available, clip will be synthesized during editing",
                },
            )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "clip.mp4"
            ffmpeg.make_color_clip(
                output,
                duration=duration,
                width=width,
                height=height,
                color=_color_from(request.prompt or "shot"),
                fps=25,
                ffmpeg_bin=self.ffmpeg_bin,
            )
            content = output.read_bytes()
        return VideoResult(
            content=content,
            mime="video/mp4",
            duration_seconds=duration,
            provider=self.name,
            model_id=self.model_id,
            cost_usd=0.0,
            meta={"offline": True, "color": _color_from(request.prompt or "shot")},
        )


class MockAudioProvider(AudioProvider):
    capability = "audio"

    def __init__(self, name: str = "mock", model_id: str = "mock-tts", options: dict | None = None) -> None:
        super().__init__(name=name, model_id=model_id, options=options)

    async def health(self) -> bool:
        return True

    async def synthesize(self, request: AudioRequest) -> AudioResult:
        duration = narrative.estimate_speech_duration(request.text)
        sample_rate = 22050
        frames = int(duration * sample_rate)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(b"\x00\x00" * frames)
        return AudioResult(
            content=buffer.getvalue(),
            mime="audio/wav",
            duration_seconds=duration,
            provider=self.name,
            model_id=self.model_id,
            cost_usd=0.0,
            meta={"offline": True, "silence": True, "text_length": len(request.text)},
        )


MOCK_PROVIDERS: dict[str, type] = {
    "llm": MockLLMProvider,
    "vision": MockVisionProvider,
    "image": MockImageProvider,
    "video": MockVideoProvider,
    "audio": MockAudioProvider,
}


def build_mock_provider(capability: str, model_id: str, options: dict[str, Any] | None = None):
    provider_class = MOCK_PROVIDERS.get(capability)
    if provider_class is None:
        raise ValueError(f"No mock provider for capability '{capability}'")
    return provider_class("mock", model_id, options)
