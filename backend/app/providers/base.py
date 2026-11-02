"""Provider interfaces.

Business code (agents/services) only ever sees these interfaces.  Adding a new
vendor means adding a provider implementation plus a YAML entry — never touching
agent logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.core.config_models import GenerationConfig


@dataclass(slots=True)
class LLMRequest:
    system: str
    user: str
    prompt_vars: dict[str, Any] = field(default_factory=dict)
    schema_name: str | None = None
    response_schema: dict[str, Any] | None = None
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    provider_options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMResult:
    text: str
    structured: dict[str, Any] | None = None
    provider: str = ""
    model_id: str = ""
    request_id: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VisionRequest:
    image_bytes: bytes
    mime: str = "image/png"
    system: str = ""
    user: str = ""
    prompt_vars: dict[str, Any] = field(default_factory=dict)
    schema_name: str | None = None
    response_schema: dict[str, Any] | None = None
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    provider_options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ImageRequest:
    prompt: str
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    count: int = 1
    model_id: str = ""
    reference_images: list[bytes] = field(default_factory=list)
    provider_options: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ImageResult:
    content: bytes
    mime: str = "image/png"
    width: int = 0
    height: int = 0
    provider: str = ""
    model_id: str = ""
    cost_usd: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VideoRequest:
    prompt: str
    negative_prompt: str = ""
    duration_seconds: float = 5.0
    aspect_ratio: str = "16:9"
    width: int = 1280
    height: int = 720
    model_id: str = ""
    reference_image: bytes | None = None
    first_frame: bytes | None = None
    last_frame: bytes | None = None
    provider_options: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VideoResult:
    content: bytes | None
    mime: str = "video/mp4"
    duration_seconds: float = 0.0
    provider: str = ""
    model_id: str = ""
    task_ref: str = ""
    cost_usd: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AudioRequest:
    text: str
    voice: str = "alloy"
    style: str = ""
    language: str = "zh"
    speed: float = 1.0
    audio_format: str = "wav"
    model_id: str = ""
    provider_options: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AudioResult:
    content: bytes
    mime: str = "audio/wav"
    duration_seconds: float = 0.0
    provider: str = ""
    model_id: str = ""
    cost_usd: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


class BaseProvider(ABC):
    capability: str = "unknown"
    name: str = "base"
    model_id: str = ""
    protocol: str = ""

    def __init__(self, name: str, model_id: str, options: dict[str, Any] | None = None) -> None:
        self.name = name
        self.model_id = model_id
        self.options = options or {}

    @property
    def capabilities(self) -> set[str]:
        return {self.capability}

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    @abstractmethod
    async def health(self) -> bool:  # pragma: no cover - trivial
        raise NotImplementedError


class LLMProvider(BaseProvider):
    capability = "llm"

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResult:
        raise NotImplementedError


class VisionProvider(BaseProvider):
    capability = "vision"

    @abstractmethod
    async def describe(self, request: VisionRequest) -> LLMResult:
        raise NotImplementedError


class ImageProvider(BaseProvider):
    capability = "image"

    @abstractmethod
    async def generate(self, request: ImageRequest) -> ImageResult:
        raise NotImplementedError


class VideoProvider(BaseProvider):
    capability = "video"

    @abstractmethod
    async def generate(self, request: VideoRequest) -> VideoResult:
        raise NotImplementedError

    async def cancel(self, task_ref: str) -> bool:  # pragma: no cover - optional capability
        return False


class AudioProvider(BaseProvider):
    capability = "audio"

    @abstractmethod
    async def synthesize(self, request: AudioRequest) -> AudioResult:
        raise NotImplementedError
