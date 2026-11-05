"""Config store: agent/provider/workflow/prompt configuration with versions."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from string import Template
from typing import Any

import yaml

from studio_platform.configuration.config_models import (
    AgentConfig,
    ProviderConfig,
    WorkflowConfig,
)
from studio_platform.configuration.settings import Settings, deep_merge
from studio_platform.exceptions import ConfigurationError


def stable_checksum(payload: Any) -> str:
    """Deterministic short hash used as configuration / prompt version."""
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]


class ConfigStore:
    """Loads YAML configuration and renders prompt templates.

    The store is process-wide but can be refreshed at runtime (admin API writes a
    new ``config_versions`` row and calls :meth:`reload`).  A *task* freezes the
    config versions it started with so results stay reproducible.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._agents: dict[str, AgentConfig] = {}
        self._providers: dict[str, dict[str, ProviderConfig]] = {}
        self._workflows: dict[str, WorkflowConfig] = {}
        self._overrides: dict[str, dict[str, Any]] = {}
        self._prompt_cache: dict[str, str] = {}
        self.reload()

    # ------------------------------------------------------------------ load
    def reload(self) -> None:
        with self._lock:
            self._agents = self._load_agents()
            self._providers = self._load_providers()
            self._workflows = self._load_workflows()
            self._prompt_cache.clear()

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:  # pragma: no cover - defensive
            raise ConfigurationError(f"Invalid YAML in {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ConfigurationError(f"{path} must contain a mapping")
        return payload

    def _load_agents(self) -> dict[str, AgentConfig]:
        agents_dir = self.settings.config_dir / "agents"
        loaded: dict[str, AgentConfig] = {}
        if not agents_dir.is_dir():
            raise ConfigurationError(f"Agent config directory missing: {agents_dir}")

        for path in sorted(agents_dir.glob("*.yaml")):
            payload = self._read_yaml(path)
            agent_id = (payload.get("agent") or {}).get("id") or path.stem
            payload = deep_merge(payload, self._overrides.get(agent_id, {}))

            # Dev/staging convenience: force a provider without editing YAML.
            forced_provider = os.getenv("AGENT_MODEL_PROVIDER")
            if forced_provider:
                payload.setdefault("model", {})["provider"] = forced_provider
                forced_model = os.getenv("AGENT_MODEL_ID")
                if forced_model:
                    payload["model"]["model_id"] = forced_model

            try:
                config = AgentConfig.model_validate(payload)
            except Exception as exc:
                raise ConfigurationError(f"Invalid agent config {path.name}: {exc}") from exc

            if config.id != agent_id:
                raise ConfigurationError(f"Agent id mismatch in {path.name}: {config.id} != {agent_id}")
            if config.id in loaded:
                raise ConfigurationError(f"Duplicate agent id '{config.id}' ({path.name})")
            config.source_path = str(path.relative_to(self.settings.config_dir)).replace("\\", "/")
            # 模型引用已在 ModelRef 校验时解析；指纹要随实际模型变化，不能只散列
            # env:VAR 这一固定占位符。保留原有字段集合及其他配置的散列/覆盖语义。
            effective_model = dict(payload.get("model") or {})
            for field in ("model_id", "fallback_model_id"):
                if field in effective_model:
                    effective_model[field] = getattr(config.model, field)
            config.config_version = stable_checksum(
                {
                    "agent": payload.get("agent"),
                    "model": effective_model,
                    "generation": payload.get("generation"),
                    "structured_output": payload.get("structured_output"),
                    "prompt": payload.get("prompt"),
                    "runtime": payload.get("runtime"),
                    "evaluation": payload.get("evaluation"),
                }
            )
            loaded[config.id] = config
        return loaded

    def _load_providers(self) -> dict[str, dict[str, ProviderConfig]]:
        providers_dir = self.settings.config_dir / "providers"
        loaded: dict[str, dict[str, ProviderConfig]] = {}
        if not providers_dir.is_dir():
            raise ConfigurationError(f"Provider config directory missing: {providers_dir}")

        for path in sorted(providers_dir.glob("*.yaml")):
            capability = path.stem
            payload = self._read_yaml(path)
            entries = payload.get("providers") or {}
            if not isinstance(entries, dict):
                raise ConfigurationError(f"providers in {path.name} must be a mapping")
            bucket: dict[str, ProviderConfig] = {}
            for name, raw in entries.items():
                raw = dict(raw or {})
                raw.setdefault("name", name)
                try:
                    bucket[name] = ProviderConfig.model_validate(
                        {**raw, "name": name, "capability": raw.get("capability", capability)}
                    )
                except Exception as exc:
                    raise ConfigurationError(f"Invalid provider '{name}' in {path.name}: {exc}") from exc
            loaded[capability] = bucket
        return loaded

    def _load_workflows(self) -> dict[str, WorkflowConfig]:
        workflows_dir = self.settings.config_dir / "workflows"
        loaded: dict[str, WorkflowConfig] = {}
        if not workflows_dir.is_dir():
            raise ConfigurationError(f"Workflow config directory missing: {workflows_dir}")
        for path in sorted(workflows_dir.glob("*.yaml")):
            payload = self._read_yaml(path)
            payload.setdefault("id", path.stem)
            payload.setdefault("name", payload["id"])
            try:
                config = WorkflowConfig.model_validate(payload)
            except Exception as exc:
                raise ConfigurationError(f"Invalid workflow config {path.name}: {exc}") from exc
            config.source_path = str(path.relative_to(self.settings.config_dir)).replace("\\", "/")
            config.config_version = stable_checksum(payload)
            loaded[config.id] = config
        return loaded

    # --------------------------------------------------------------- access
    def agent_ids(self) -> list[str]:
        return sorted(self._agents)

    def agent(self, agent_id: str) -> AgentConfig:
        with self._lock:
            config = self._agents.get(agent_id)
        if config is None:
            raise ConfigurationError(f"Unknown agent '{agent_id}'")
        if not config.enabled:
            raise ConfigurationError(f"Agent '{agent_id}' is disabled in its config file")
        return config

    def try_agent(self, agent_id: str) -> AgentConfig | None:
        return self._agents.get(agent_id)

    @property
    def agents(self) -> dict[str, AgentConfig]:
        return dict(self._agents)

    def provider(self, capability: str, name: str) -> ProviderConfig:
        bucket = self._providers.get(capability) or {}
        config = bucket.get(name)
        if config is None:
            raise ConfigurationError(f"Unknown {capability} provider '{name}'")
        return config

    def providers(self, capability: str | None = None) -> dict[str, ProviderConfig]:
        if capability:
            return dict(self._providers.get(capability) or {})
        flat: dict[str, ProviderConfig] = {}
        for bucket in self._providers.values():
            for name, config in bucket.items():
                flat[f"{config.capability}:{name}"] = config
        return flat

    def workflow(self, workflow_id: str) -> WorkflowConfig:
        config = self._workflows.get(workflow_id)
        if config is None:
            raise ConfigurationError(f"Unknown workflow '{workflow_id}'")
        return config

    def workflows(self) -> dict[str, WorkflowConfig]:
        return dict(self._workflows)

    def default_workflow_id(self) -> str:
        return self.settings.get("workflows", "default", default="novel_to_video")

    def config_versions(self) -> dict[str, str]:
        """Snapshot used to freeze a task/run to the configuration it started with."""
        return {
            f"agent:{agent_id}": config.config_version for agent_id, config in sorted(self._agents.items())
        }

    def agent_configs_public(self) -> list[dict[str, Any]]:
        return [config.model_dump_public() for _, config in sorted(self._agents.items())]

    def apply_overrides(self, overrides: dict[str, dict[str, Any]]) -> None:
        """Apply DB-backed overrides (admin model-config page) and reload."""
        self._overrides = overrides
        self.reload()

    # --------------------------------------------------------------- prompts
    def prompt_text(self, relative_path: str) -> str:
        with self._lock:
            if relative_path in self._prompt_cache:
                return self._prompt_cache[relative_path]
        path = (self.settings.config_dir / relative_path).resolve()
        try:
            path.relative_to(self.settings.config_dir)
        except ValueError as exc:
            raise ConfigurationError(f"Prompt path escapes config dir: {relative_path}") from exc
        if not path.is_file():
            raise ConfigurationError(f"Prompt template missing: {relative_path}")
        text = path.read_text(encoding="utf-8")
        with self._lock:
            self._prompt_cache[relative_path] = text
        return text

    def prompt_version(self, *relative_paths: str) -> str:
        payload = {path: self.prompt_text(path) for path in relative_paths}
        return stable_checksum(payload)

    def render_prompts(self, config: AgentConfig, variables: dict[str, Any]) -> tuple[str, str, str]:
        """Render system + user prompts, returning (system, user, prompt_version)."""
        system_template = self.prompt_text(config.prompt.system)
        user_template = self.prompt_text(config.prompt.user_template)
        flat = {key: _stringify(value) for key, value in variables.items()}
        system = Template(system_template).safe_substitute(flat)
        user = Template(user_template).safe_substitute(flat)
        return system, user, self.prompt_version(config.prompt.system, config.prompt.user_template)


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)
