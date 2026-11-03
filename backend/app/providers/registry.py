"""Provider registry/factory.

Resolves a configured provider name (from an agent YAML) into a concrete
implementation.  Agents never import provider implementations directly.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.core.config_models import GenerationConfig, ModelRef, ProviderConfig
from app.core.config_store import ConfigStore
from app.core.exceptions import ConfigurationError, ProviderUnavailableError
from app.providers.base import (
    AudioProvider,
    ImageProvider,
    LLMProvider,
    VideoProvider,
    VisionProvider,
)
from app.providers.mock import build_mock_provider
from app.providers.openai_compat import (
    HttpTaskVideoProvider,
    LocalWorkerVideoProvider,
    OpenAICompatibleLLMProvider,
    OpenAICompatibleVisionProvider,
    OpenAIImageProvider,
    OpenAISpeechProvider,
    OpenAIVideosProvider,
)

logger = logging.getLogger(__name__)

_PROTOCOL_IMPLS: dict[tuple[str, str], type] = {
    ("llm", "openai_chat"): OpenAICompatibleLLMProvider,
    ("vision", "openai_chat"): OpenAICompatibleVisionProvider,
    ("image", "openai_images"): OpenAIImageProvider,
    ("audio", "openai_speech"): OpenAISpeechProvider,
    ("video", "http_task"): HttpTaskVideoProvider,
    ("video", "openai_videos"): OpenAIVideosProvider,
    ("video", "local_worker"): LocalWorkerVideoProvider,
}

_SUPPORTED_PARAMS = {"temperature", "top_p", "seed", "max_output_tokens", "timeout_seconds"}


def _mock_provider_config(capability: str, name: str) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        capability=capability,
        enabled=True,
        protocol="mock",
        timeout_seconds=120,
        max_concurrency=4,
    )


def resolve_provider_config(config_store: ConfigStore, capability: str, name: str) -> ProviderConfig:
    if name == "mock":
        try:
            return config_store.provider(capability, name)
        except ConfigurationError:
            return _mock_provider_config(capability, name)
    config = config_store.provider(capability, name)
    if not config.enabled:
        raise ProviderUnavailableError(
            f"Provider '{name}' ({capability}) is disabled in its config file; set `enabled: true`",
            details={"provider": name, "capability": capability},
        )
    if config.declares_api_key() and not config.resolved_api_key():
        source = config.api_key_source()
        raise ProviderUnavailableError(
            f"Provider '{name}' is enabled but no API key was found; set `{source}` in .env",
            details={"provider": name, "api_key": source},
        )
    return config


def _provider_options(config_store: ConfigStore, config: ProviderConfig, model: ModelRef) -> dict[str, Any]:
    settings = getattr(config_store, "settings", None)
    options: dict[str, Any] = {
        "api_key": config.resolved_api_key(),
        "base_url": config.resolved_url(),
        "timeout_seconds": config.timeout_seconds,
        "max_concurrency": config.max_concurrency,
        # Resolved once in settings so mock/real media providers agree on the binary.
        "ffmpeg_bin": getattr(settings, "ffmpeg_bin", None) or os.getenv("FFMPEG_BIN", "ffmpeg"),
        "ffprobe_bin": getattr(settings, "ffprobe_bin", None) or os.getenv("FFPROBE_BIN", "ffprobe"),
    }
    # 模块 1：合并顺序 = 基础字段 -> 供应商 extra -> 模型级 provider_options（后者覆盖前者）。
    # 智能体的 generation 字段不在这里，由各 provider 内部拼进请求体。
    options.update(config.extra or {})
    endpoint = config.resolved_endpoint()
    if endpoint:
        options.setdefault("endpoint", endpoint)
    if config.capability == "video":
        options["base_url"] = config.resolved_url() or config.resolved_endpoint()
    options.update(model.provider_options or {})
    return options


def build_provider(config_store: ConfigStore, capability: str, model: ModelRef):
    config = resolve_provider_config(config_store, capability, model.provider)
    if config.protocol_name() == "mock" or model.provider == "mock":
        return build_mock_provider(capability, model.model_id, _provider_options(config_store, config, model))

    if config.models and model.model_id not in config.models:
        message = (
            f"Model '{model.model_id}' is not listed for provider '{config.name}' "
            f"({config.capability}); known models: {', '.join(config.models)}"
        )
        if config.extra.get("strict_models"):
            raise ConfigurationError(message)
        logger.warning(message)

    protocol = config.protocol_name()
    impl = _PROTOCOL_IMPLS.get((capability, protocol))
    if impl is None:
        raise ConfigurationError(
            f"Provider '{config.name}' declares protocol '{protocol}' which does not support "
            f"capability '{capability}'"
        )
    return impl(config.name, model.model_id, _provider_options(config_store, config, model))


def get_llm(config_store: ConfigStore, model: ModelRef) -> LLMProvider:
    provider = build_provider(config_store, "llm", model)
    if not isinstance(provider, LLMProvider):
        raise ConfigurationError(f"Provider '{model.provider}' is not an LLM provider")
    return provider


def get_vision(config_store: ConfigStore, model: ModelRef) -> VisionProvider:
    provider = build_provider(config_store, "vision", model)
    if not isinstance(provider, VisionProvider):
        raise ConfigurationError(f"Provider '{model.provider}' is not a vision provider")
    return provider


def get_image(config_store: ConfigStore, model: ModelRef) -> ImageProvider:
    provider = build_provider(config_store, "image", model)
    if not isinstance(provider, ImageProvider):
        raise ConfigurationError(f"Provider '{model.provider}' is not an image provider")
    return provider


def get_video(config_store: ConfigStore, model: ModelRef) -> VideoProvider:
    provider = build_provider(config_store, "video", model)
    if not isinstance(provider, VideoProvider):
        raise ConfigurationError(f"Provider '{model.provider}' is not a video provider")
    return provider


def get_audio(config_store: ConfigStore, model: ModelRef) -> AudioProvider:
    provider = build_provider(config_store, "audio", model)
    if not isinstance(provider, AudioProvider):
        raise ConfigurationError(f"Provider '{model.provider}' is not an audio provider")
    return provider


def validate_generation(
    config_store: ConfigStore, capability: str, model: ModelRef, generation: GenerationConfig
) -> None:
    """Reject parameters that the provider explicitly declares unsupported.

    Providers may declare ``supported_params`` in their YAML.  Unknown parameters
    are a hard error instead of silently changing model behaviour.
    """
    try:
        config = resolve_provider_config(config_store, capability, model.provider)
    except ProviderUnavailableError:
        raise
    supported = config.extra.get("supported_params")
    if not supported:
        return
    supported_set = set(supported)
    for param in ("temperature", "top_p", "seed", "max_output_tokens"):
        value = getattr(generation, param)
        if value is None:
            continue
        if param not in supported_set:
            raise ConfigurationError(
                f"Provider '{config.name}' does not support '{param}'; "
                f"remove it from the agent config or move it to provider_options"
            )


def provider_concurrency(config_store: ConfigStore, capability: str, name: str) -> int:
    try:
        config = config_store.provider(capability, name)
    except ConfigurationError:
        return 1
    return max(1, config.max_concurrency)
