"""Agent framework.

Design rules enforced here:

* every agent validates structured input and output against a Pydantic schema;
* model/provider selection comes from configuration only (never hard-coded);
* invalid output is repaired/retried and falls back to the configured backup
  model before it can reach a downstream agent;
* latency, token usage, cost and config/prompt versions are recorded per run.
"""

from __future__ import annotations

import asyncio
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config_models import AgentConfig, ModelRef
from app.core.config_store import ConfigStore
from app.core.exceptions import AgentSchemaError, ProviderError
from app.providers import registry as provider_registry
from app.providers.base import LLMRequest, LLMResult, VisionRequest

InT = TypeVar("InT", bound=BaseModel)
OutT = TypeVar("OutT", bound=BaseModel)


@dataclass(slots=True)
class AgentContext:
    project_id: str
    task_id: str = ""
    workflow_run_id: str = ""
    user_id: str = ""
    config_versions: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentResult:
    output: Any
    provider: str = ""
    model_id: str = ""
    prompt_version: str = ""
    config_version: str = ""
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    attempts: int = 1
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def data(self) -> dict[str, Any]:
        if isinstance(self.output, BaseModel):
            return self.output.model_dump(mode="json")
        if isinstance(self.output, dict):
            return self.output
        return {"value": self.output}

    @property
    def summary(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "prompt_version": self.prompt_version,
            "config_version": self.config_version,
            "latency_ms": round(self.latency_ms, 1),
            "cost_usd": self.cost_usd,
            "attempts": self.attempts,
        }


class BaseAgent(ABC, Generic[InT, OutT]):
    agent_id: ClassVar[str] = ""
    input_model: ClassVar[type[BaseModel]] = BaseModel
    output_model: ClassVar[type[BaseModel]] = BaseModel
    capability: ClassVar[str] = "llm"

    def __init__(self, config_store: ConfigStore, config: AgentConfig | None = None) -> None:
        self.config_store = config_store
        self.config = config or config_store.agent(self.agent_id)

    # ------------------------------------------------------------- lifecycle
    def load_config(self) -> AgentConfig:
        return self.config

    def validate_input(self, payload: dict[str, Any] | BaseModel) -> InT:
        if isinstance(payload, self.input_model):
            return payload  # type: ignore[return-value]
        if isinstance(payload, BaseModel):
            # Python mode keeps binary payloads (reference frames) untouched.
            payload = payload.model_dump()
        return self.input_model.model_validate(payload)  # type: ignore[return-value]

    def validate_output(self, payload: dict[str, Any] | BaseModel) -> OutT:
        if isinstance(payload, self.output_model):
            return payload  # type: ignore[return-value]
        if isinstance(payload, BaseModel):
            payload = payload.model_dump()
        return self.output_model.model_validate(payload)  # type: ignore[return-value]

    @abstractmethod
    async def execute(self, inputs: InT, ctx: AgentContext) -> AgentResult:
        raise NotImplementedError

    async def evaluate(self, output: BaseModel, ctx: AgentContext) -> dict[str, Any]:
        """Cheap heuristic quality gate; deeper evaluation is a separate agent."""
        if not self.config.evaluation.enabled:
            return {"enabled": False}
        warnings: list[str] = []
        meaningful = 0
        total = 0
        for name, value in output.model_dump().items():
            if name.startswith("_") or value is None:
                continue
            total += 1
            if isinstance(value, str):
                meaningful += 1 if value.strip() else 0
                if not value.strip():
                    warnings.append(f"empty field: {name}")
            elif isinstance(value, (list, dict)):
                meaningful += 1 if value else 0
                if not value:
                    warnings.append(f"empty collection: {name}")
            else:
                meaningful += 1
        completeness = round(meaningful / max(1, total), 3)
        return {
            "enabled": True,
            "schema_valid": True,
            "completeness": completeness,
            "warnings": warnings[:8],
            "checks": self.config.evaluation.checks,
        }


class StructuredLLMAgent(BaseAgent):
    """Agent whose output is a JSON object validated against ``output_model``."""

    schema_name: ClassVar[str] = ""
    system_variables: ClassVar[tuple[str, ...]] = ()

    def build_variables(self, inputs: InT, ctx: AgentContext) -> dict[str, Any]:
        return inputs.model_dump(mode="json")

    def postprocess(self, output: OutT, inputs: InT, ctx: AgentContext) -> OutT:
        return output

    async def execute(self, inputs: InT, ctx: AgentContext) -> AgentResult:
        variables = self.build_variables(inputs, ctx)
        return await self.invoke(
            variables=variables,
            ctx=ctx,
            schema_name=self.schema_name,
            output_model=self.output_model,
            inputs=inputs,
        )

    # -------------------------------------------------------------- internals
    def _provider_for(self, model_ref: ModelRef):
        return provider_registry.get_llm(self.config_store, model_ref)

    async def _call(self, provider, request) -> LLMResult:
        return await provider.generate(request)

    async def invoke(
        self,
        *,
        variables: dict[str, Any],
        ctx: AgentContext,
        schema_name: str,
        output_model: type[BaseModel],
        inputs: InT | None = None,
        image_bytes: bytes | None = None,
        image_mime: str = "image/png",
    ) -> AgentResult:
        started = time.perf_counter()
        provider_registry.validate_generation(
            self.config_store, self.capability, self.config.model, self.config.generation
        )
        system_prompt, user_prompt, prompt_version = self.config_store.render_prompts(
            self.config, variables
        )
        response_schema = output_model.model_json_schema()
        # 模块 2 关键点：把输出 schema 写进 system prompt。
        # 多数兼容 OpenAI 的本地服务只实现了 response_format=json_object（不校验字段名），
        # 模型看不到 schema 就会自己发明字段（例如 dialogues 里写 speaker 而不是
        # character_name），校验必然失败，还白白消耗重试/修复额度。
        system_prompt = (
            f"{system_prompt}\n\n[输出 JSON Schema：字段名与类型必须完全一致]\n"
            + json.dumps(response_schema, ensure_ascii=False, separators=(",", ":"))
        )

        candidates: list[ModelRef] = [self.config.model]
        fallback = self.config.model.fallback
        if fallback:
            candidates.append(fallback)

        attempts = 0
        failures: list[str] = []
        max_attempts = max(1, self.config.generation.max_retries + 1)
        repair_attempts = max(0, self.config.structured_output.repair_attempts)
        cost = 0.0
        tokens_in = 0
        tokens_out = 0
        model_used = self.config.model
        provider_used = ""

        for candidate in candidates:
            try:
                provider = self._provider_for(candidate)
            except Exception as exc:  # provider unavailable / misconfigured
                failures.append(f"{candidate.provider}: {exc}")
                continue
            current_user_prompt = user_prompt
            repair_used = 0
            for attempt in range(1, max_attempts + 1):
                attempts += 1
                request_kwargs = dict(
                    system=system_prompt,
                    user=current_user_prompt,
                    prompt_vars=variables,
                    schema_name=schema_name,
                    response_schema=response_schema,
                    generation=self.config.generation,
                    provider_options=candidate.provider_options,
                )
                try:
                    if image_bytes is not None:
                        result = await provider.describe(
                            VisionRequest(
                                image_bytes=image_bytes,
                                mime=image_mime,
                                **request_kwargs,
                            )
                        )
                    else:
                        result = await provider.generate(LLMRequest(**request_kwargs))
                except ProviderError as exc:
                    failures.append(f"{candidate.provider}/{candidate.model_id}: {exc}")
                    if attempt < max_attempts:
                        await asyncio.sleep(min(0.8, 0.1 * attempt))
                        continue
                    break

                cost += result.cost_usd
                tokens_in += result.tokens_in
                tokens_out += result.tokens_out
                provider_used = result.provider or candidate.provider
                payload = result.structured
                if payload is None:
                    payload = _parse_json(result.text)
                try:
                    if payload is None:
                        raise ValueError("provider returned no structured payload")
                    parsed = output_model.model_validate(payload)
                    if inputs is not None and hasattr(self, "postprocess"):
                        parsed = self.postprocess(parsed, inputs, ctx)  # type: ignore[arg-type]
                    latency_ms = (time.perf_counter() - started) * 1000
                    return AgentResult(
                        output=parsed,
                        provider=provider_used,
                        model_id=result.model_id or candidate.model_id,
                        prompt_version=prompt_version,
                        config_version=self.config.config_version,
                        latency_ms=latency_ms,
                        cost_usd=round(cost, 6),
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        attempts=attempts,
                        meta={
                            "schema": schema_name,
                            "request_id": result.request_id,
                            "provider_meta": result.meta,
                            "repairs": repair_used,
                            "degraded": candidate is not self.config.model,
                        },
                    )
                except (ValidationError, ValueError) as exc:
                    failures.append(f"schema validation failed: {exc}")
                    model_used = candidate
                    # 模块 2 关键点：这里决定"模型胡输出"会怎样收场。
                    # attempts 统计真实 HTTP 调用次数；repair 只在既有重试额度
                    # （max_retries）又还有 repair_attempts 时触发，且会把校验错误
                    # 追加进 user prompt。额度用尽就抛 AgentSchemaError（带 details），
                    # 绝不让不合契约的数据流给下游智能体。
                    if repair_used < repair_attempts and attempt < max_attempts:
                        repair_used += 1
                        current_user_prompt = (
                            f"{user_prompt}\n\n"
                            "上一次输出没有通过结构化校验，请只返回严格符合 JSON Schema 的 JSON，"
                            "不要输出解释文字。\n"
                            f"校验错误：{str(exc)[:800]}"
                        )
                        continue
                    break

        latency_ms = (time.perf_counter() - started) * 1000
        raise AgentSchemaError(
            f"Agent '{self.agent_id}' failed to produce schema '{schema_name}'",
            details={
                "attempts": attempts,
                "provider": provider_used or model_used.provider,
                "model_id": model_used.model_id,
                "failures": failures[-4:],
                "latency_ms": round(latency_ms, 1),
            },
        )


class StructuredVisionAgent(StructuredLLMAgent):
    capability: ClassVar[str] = "vision"
    schema_name: ClassVar[str] = "character_vision"

    def _provider_for(self, model_ref: ModelRef):
        return provider_registry.get_vision(self.config_store, model_ref)


class MediaAgent(BaseAgent):
    """Base class for agents that call media providers (image/video/audio)."""

    capability: ClassVar[str] = "image"

    def _model_ref(self) -> ModelRef:
        return self.config.model


def _parse_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.lower().startswith("json"):
            candidate = candidate[4:]
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
