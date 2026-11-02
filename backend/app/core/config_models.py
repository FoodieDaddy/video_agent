"""Typed configuration objects.

Every agent owns an independent YAML file in ``config/agents``.  An agent never
hard-codes a model name: it only knows its own agent id, and the model registry
resolves provider + model + parameters from these objects.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ``url: env:SOME_VAR`` / ``api_key: env:SOME_VAR`` reads the value from the
# environment; a bare value is used verbatim (so a base URL, or even a key, may
# be typed straight into the provider file).
ENV_REF_PREFIX = "env:"


def resolve_ref(value: str | None) -> str | None:
    """Return a literal config value, resolving ``env:NAME`` references."""
    if not value:
        return None
    text = str(value).strip()
    if text.lower().startswith(ENV_REF_PREFIX):
        return os.getenv(text[len(ENV_REF_PREFIX) :].strip()) or None
    return text or None


class AgentMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    enabled: bool = True
    version: str = "1.0.0"
    description: str = ""


class ModelRef(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: str
    model_id: str
    capability: str = "text_reasoning"
    fallback_provider: str | None = None
    fallback_model_id: str | None = None
    provider_options: dict[str, Any] = Field(default_factory=dict)

    @property
    def fallback(self) -> ModelRef | None:
        if self.fallback_provider and self.fallback_model_id:
            return ModelRef(
                provider=self.fallback_provider,
                model_id=self.fallback_model_id,
                capability=self.capability,
                provider_options=self.provider_options,
            )
        return None


class GenerationConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    temperature: float | None = None
    top_p: float | None = None
    seed: int | None = None
    max_output_tokens: int | None = None
    timeout_seconds: int = 120
    max_retries: int = 2


class StructuredOutputConfig(BaseModel):
    enabled: bool = True
    schema_name: str | None = None
    validation_required: bool = True
    repair_attempts: int = 1


class PromptRef(BaseModel):
    system: str
    user_template: str
    version: str = "1.0.0"


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    concurrency: int = 1
    cache_enabled: bool = False
    human_review_required: bool = False


class EvaluationConfig(BaseModel):
    enabled: bool = True
    checks: list[str] = Field(default_factory=list)
    thresholds: dict[str, float] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    agent: AgentMeta
    model: ModelRef
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    structured_output: StructuredOutputConfig = Field(default_factory=StructuredOutputConfig)
    prompt: PromptRef
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)

    config_version: str = ""
    source_path: str = ""

    @property
    def id(self) -> str:
        return self.agent.id

    @property
    def enabled(self) -> bool:
        return self.agent.enabled

    def model_dump_public(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload["config_version"] = self.config_version
        payload["source_path"] = self.source_path
        return payload


class ProviderConfig(BaseModel):
    """One provider entry in ``config/providers/<capability>.yaml``.

    Field names are the plain ones an operator looks for: ``url``, ``api_key``,
    ``protocol``.  Either may be written as ``env:NAME`` to read the value from an
    environment variable instead.  The old ``kind`` / ``api_key_env`` /
    ``base_url_env`` / ``base_url`` spelling is still accepted for compatibility.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    capability: str
    enabled: bool = False
    # openai_chat | openai_images | openai_speech | http_task | local_worker | mock
    protocol: str = ""
    url: str | None = None
    api_key: str | None = None
    endpoint: str | None = None
    timeout_seconds: int = 120
    max_concurrency: int = 2
    models: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    # --- legacy spelling (kept so an existing provider file still loads) ---
    kind: str = ""
    api_key_env: str | None = None
    base_url_env: str | None = None
    base_url: str | None = None
    endpoint_env: str | None = None

    def protocol_name(self) -> str:
        return str(self.extra.get("protocol") or self.protocol or self.kind or "")

    def declares_api_key(self) -> bool:
        return bool(self.api_key or self.api_key_env)

    def api_key_source(self) -> str:
        """Name of the thing holding the key - for messages, never the key itself."""
        if self.api_key_env:
            return self.api_key_env
        text = str(self.api_key or "").strip()
        if not text:
            return ""
        if text.lower().startswith(ENV_REF_PREFIX):
            return text[len(ENV_REF_PREFIX) :].strip()
        return "api_key in the provider file"

    def resolved_api_key(self) -> str | None:
        value = resolve_ref(self.api_key)
        if value:
            return value
        return os.getenv(self.api_key_env) if self.api_key_env else None

    def resolved_url(self, default: str | None = None) -> str | None:
        value = resolve_ref(self.url)
        if value:
            return value
        if self.base_url_env and os.getenv(self.base_url_env):
            return os.getenv(self.base_url_env)
        return self.base_url or default

    # Kept for callers written against the old name.
    def resolved_base_url(self, default: str | None = None) -> str | None:
        return self.resolved_url(default)

    def resolved_endpoint(self) -> str | None:
        value = resolve_ref(self.endpoint)
        if value:
            return value
        if self.endpoint_env and os.getenv(self.endpoint_env):
            return os.getenv(self.endpoint_env)
        return self.extra.get("endpoint")


class WorkflowNodeConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: str = "handler"  # handler | gate
    handler: str | None = None
    agent: str | None = None
    review_stage: str | None = None
    title: str = ""
    continue_on_error: bool = False
    repeat: int = 1


class WorkflowConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    nodes: list[WorkflowNodeConfig] = Field(default_factory=list)
    config_version: str = ""
    source_path: str = ""

    def node_by_id(self, node_id: str) -> WorkflowNodeConfig | None:
        return next((node for node in self.nodes if node.id == node_id), None)

    def next_node(self, node_id: str) -> WorkflowNodeConfig | None:
        for index, node in enumerate(self.nodes):
            if node.id == node_id:
                return self.nodes[index + 1] if index + 1 < len(self.nodes) else None
        return None
