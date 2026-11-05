"""Agent 执行契约与结构化调用基类。

本模块负责输入输出结构校验、提示词组装，以及配置允许的重试、修复和备用
候选选择。版本字段用于追踪配置身份，不代表完整配置或工作流已经冻结。
用量来自 Provider 返回值，审计、预算落库与事务由应用执行协调负责。
结构合法、后处理非空或启发式评估通过，都不等于内容事实正确。
"""

from __future__ import annotations

import asyncio
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from studio_ai_runtime.providers import registry as provider_registry
from studio_ai_runtime.providers.base import LLMRequest, LLMResult, VisionRequest
from studio_platform.configuration.config_models import AgentConfig, ModelRef
from studio_platform.configuration.config_store import ConfigStore
from studio_platform.exceptions import AgentSchemaError, ProviderError

InT = TypeVar("InT", bound=BaseModel)
OutT = TypeVar("OutT", bound=BaseModel)


@dataclass(slots=True)
class AgentContext:
    """一次执行的业务归属与附加上下文，不持有数据库 Session。

    Attributes:
        project_id、task_id、workflow_run_id、user_id：调用方已经鉴权的业务标识；
            未关联任务或工作流时相应字段可为空，本对象不另行校验归属或权限。
        config_versions：调用方记录的版本指纹，不包含完整配置快照。
        extra：由具体用例约定的附加数据；公共基类不保证其 Schema 或取消语义。
    """

    project_id: str
    task_id: str = ""
    workflow_run_id: str = ""
    user_id: str = ""
    config_versions: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentResult:
    """候选产物及执行证据，由应用层决定如何持久化。

    Attributes:
        output：具体 Agent 的结构化结果或媒体结果；本类型不自行保存二进制。
        provider、model_id：Provider 返回或执行器补入的标识，不独立证明服务端模型身份。
        prompt_version、config_version：本次使用的内容或配置指纹。
        latency_ms：执行耗时，单位毫秒；可包含重试等待，不是统一网络时延。
        tokens_in、tokens_out：累计可取得的 Provider usage；mock/stub 也可提供估算值。
        cost_usd：按已配置费率累计的美元估算，零值可能表示尚未配置费率。
        attempts：Provider 执行尝试次数；mock/stub 同样计数，不等于真实 HTTP 请求数。
        meta：实现专用证据。结构化基类的 repairs 只记录成功候选的修复次数，
            degraded 表示选择了备用候选，不是对内容质量作出的评定。
    """

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
        """将结构化 output 转为字典；媒体审计应使用专用序列化接口。

        不写存储；Pydantic 的 JSON 模式可能拒绝不能编码的二进制字段。
        """
        if isinstance(self.output, BaseModel):
            return self.output.model_dump(mode="json")
        if isinstance(self.output, dict):
            return self.output
        return {"value": self.output}

    @property
    def summary(self) -> dict[str, Any]:
        """返回不含产物正文的执行摘要，不执行计费或质量判断。"""
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
    """具体业务 Agent 的公共生命周期契约。

    调用方先校验输入，再执行并按需评估。构造时保存当前配置对象引用，
    不深拷贝 ConfigStore，也不建立持久化快照或数据库事务。
    """

    agent_id: ClassVar[str] = ""
    input_model: ClassVar[type[BaseModel]] = BaseModel
    output_model: ClassVar[type[BaseModel]] = BaseModel
    capability: ClassVar[str] = "llm"

    def __init__(self, config_store: ConfigStore, config: AgentConfig | None = None) -> None:
        self.config_store = config_store
        self.config = config or config_store.agent(self.agent_id)

    # ------------------------------------------------------------- 生命周期
    def load_config(self) -> AgentConfig:
        """返回构造时选定的内存配置对象，不重新读取 YAML 或 .env。"""
        return self.config

    def validate_input(self, payload: dict[str, Any] | BaseModel) -> InT:
        """按 input_model 校验输入，返回对应 Pydantic 对象。

        字典或其他 BaseModel 会转换后校验；已是目标类型时直接返回，不复制对象。
        非法字段由 Pydantic 抛 ValidationError，尚未开始模型调用或审计落库。
        """
        if isinstance(payload, self.input_model):
            return payload  # type: ignore[return-value]
        if isinstance(payload, BaseModel):
            # Python 模式保留参考图等原始 bytes，后续再按目标模型校验。
            payload = payload.model_dump()
        return self.input_model.model_validate(payload)  # type: ignore[return-value]

    def validate_output(self, payload: dict[str, Any] | BaseModel) -> OutT:
        """按 output_model 校验结构；字段合法不表示事实与业务引用正确。

        非法结构抛 Pydantic ValidationError；已是目标类型时直接返回该对象。
        """
        if isinstance(payload, self.output_model):
            return payload  # type: ignore[return-value]
        if isinstance(payload, BaseModel):
            payload = payload.model_dump()
        return self.output_model.model_validate(payload)  # type: ignore[return-value]

    @abstractmethod
    async def execute(self, inputs: InT, ctx: AgentContext) -> AgentResult:
        """执行已准备的输入并返回 AgentResult，由具体 Agent 实现。

        调用者负责先验证输入以及后续持久化、事务和资源预算。抽象方法本身
        抛 NotImplementedError；具体实现的 Provider/校验异常应由调用边界处理。
        """
        raise NotImplementedError

    async def evaluate(self, output: BaseModel, ctx: AgentContext) -> dict[str, Any]:
        """计算顶层字段非空率的启发式摘要，不阻断生产流程。

        Args:
            output: 可 model_dump 的 Pydantic 输出。
            ctx: 本次执行上下文，当前未用于评估判断。

        Returns:
            关闭时为 enabled=False，否则包含完整率、最多八条空字段提示及
            原样回显的 checks；当前不执行各项 checks 的事实核查或 thresholds 门槛。

        Notes:
            不联网、不写数据库，不深度比较引用或验证媒体内容。
        """
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
    """使用 output_model 验证 JSON 对象的 Agent 基类。"""

    schema_name: ClassVar[str] = ""
    system_variables: ClassVar[tuple[str, ...]] = ()

    def build_variables(self, inputs: InT, ctx: AgentContext) -> dict[str, Any]:
        """从已验证输入建立提示词变量；子类可在此选择相关上下文。"""
        return inputs.model_dump(mode="json")

    def postprocess(self, output: OutT, inputs: InT, ctx: AgentContext) -> OutT:
        """子类可补全或约束已解析输出；默认保持原对象，不替代事实核查。"""
        return output

    async def execute(self, inputs: InT, ctx: AgentContext) -> AgentResult:
        """将已验证输入转为变量后执行结构化调用，异常与副作用见 invoke。"""
        variables = self.build_variables(inputs, ctx)
        return await self.invoke(
            variables=variables,
            ctx=ctx,
            schema_name=self.schema_name,
            output_model=self.output_model,
            inputs=inputs,
        )

    # -------------------------------------------------------------- 内部辅助
    def _provider_for(self, model_ref: ModelRef):
        return provider_registry.get_llm(self.config_store, model_ref)

    async def _call(self, provider, request) -> LLMResult:
        """保留的直接 Provider 调用辅助；当前 invoke 主路径自行选择 generate/describe。"""
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
        """调用候选模型、验证结构，并在配置额度内修复或切换备用候选。

        Args:
            variables: 渲染当前配置提示词的纯数据。
            ctx: 仅携带业务标识及附加信息的执行上下文。
            schema_name: 结果的 Schema 标识。
            output_model: 实际执行 Pydantic 校验的结果类型。
            inputs: 提供时传给 postprocess。
            image_bytes: 非 None 时调用视觉 describe，否则调用文字 generate。
            image_mime: 图像输入的编码类型。

        Returns:
            成功的 AgentResult。tokens 和费用只累计成功返回 LLMResult 的尝试；
            失败请求已产生但未返回的 usage 不在此保证完整计入。

        Raises:
            AgentSchemaError: 所有候选不可用或配置额度内无法取得合法结果。
            其他异常: 主配置预检错误、未转换的底层异常和协程取消直接传播。
                构造候选失败会记入 failures 后尝试下一候选；ProviderError 在每候选
                max_retries+1 次额度内重试，输出校验失败仅在剩余额度与
                repair_attempts 均允许时追加修复要求。

        Notes:
            可能执行多次收费模型请求和重试等待，不写数据库或提交业务结果。
            repair 消耗已有尝试额度，每个备用候选重新获得其候选内修复计数。
            HTTP 超时由具体 Provider 配置，本方法没有统一总 deadline 或取消令牌，
            不负责取消已经创建的远端作业。
        """
        started = time.perf_counter()
        provider_registry.validate_generation(
            self.config_store, self.capability, self.config.model, self.config.generation
        )
        system_prompt, user_prompt, prompt_version = self.config_store.render_prompts(self.config, variables)
        response_schema = output_model.model_json_schema()
        # 模块 2 关键点：把输出 schema 写进 system prompt。
        # 多数兼容 OpenAI 的本地服务只实现了 response_format=json_object（不校验字段名），
        # 模型看不到 schema 就会自己发明字段（例如 dialogues 里写 speaker 而不是
        # character_name），校验必然失败，还白白消耗重试/修复额度。
        system_prompt = f"{system_prompt}\n\n[输出 JSON Schema：字段名与类型必须完全一致]\n" + json.dumps(
            response_schema, ensure_ascii=False, separators=(",", ":")
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
            except Exception as exc:  # 当前候选构造不可用或配置不匹配
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
                    # 尝试数统计 Provider 方法调用，mock/stub 也计数。修复使用本候选
                    # 已有尝试额度，并把结构错误追加到 user prompt；不扩充总额度。
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
    """沿用结构化校验与修复流程，通过视觉 Provider 处理图像输入。"""

    capability: ClassVar[str] = "vision"
    schema_name: ClassVar[str] = "character_vision"

    def _provider_for(self, model_ref: ModelRef):
        return provider_registry.get_vision(self.config_store, model_ref)


class MediaAgent(BaseAgent):
    """图像、视频或音频 Agent 的基类；调用与取消行为由具体实现承担。"""

    capability: ClassVar[str] = "image"

    def _model_ref(self) -> ModelRef:
        return self.config.model


def _parse_json(text: str) -> dict[str, Any] | None:
    """尝试从文本首个左括号到末个右括号解析对象；失败返回 None，不做修复。"""
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
