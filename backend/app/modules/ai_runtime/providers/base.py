"""模型能力的请求、结果与异步接口。

这些类型不拥有数据库事务。具体 Provider 负责协议转换和外部调用，Agent
负责输入输出校验，应用用例负责产物提交、业务状态、预算和任务取消协调。
接口不统一保证所有网络错误被包装，调用方须按具体实现约定处理异常。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.modules.platform.configuration.config_models import GenerationConfig


@dataclass(slots=True)
class LLMRequest:
    """文字生成请求，不等同于完整对话或工具循环协议。

    system/user 是当前调用文本；prompt_vars/schema_name 是结构化用途的附加信息。
    response_schema 是否仅触发 JSON 模式、是否执行字段校验由实现说明；应用仍需
    校验结果。generation 描述生成参数，provider_options 的使用范围也由实现决定。
    """

    system: str
    user: str
    prompt_vars: dict[str, Any] = field(default_factory=dict)
    schema_name: str | None = None
    response_schema: dict[str, Any] | None = None
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    provider_options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMResult:
    """文字或视觉结果及 Provider 返回的用量证据。

    text 为原始文本，structured 可为空；指纹和业务校验由 Agent 层补充。
    model_id/provider 是实现声明的标识，不是独立后端身份认证。
    tokens_in/out 为服务返回或实现估算的 token 数；cost_usd 是已配置费率下的
    美元估算，零值不证明免费。meta 保留实现专用证据，不代替业务资产或审计表。
    """

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
    """图像 bytes 与文字上下文；mime 说明图像编码，可能经外部网络发送。"""

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
    """图像生成输入；尺寸单位为像素，参考图为内存 bytes。

    count 为候选数量请求，不保证实现返回全部候选；实际支持的模型、尺寸和
    provider_options 由 Provider 决定。meta 用于实现约定，不自动成为模型参数。
    """

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
    """编码图像 bytes 与尺寸元信息；不表示文件已经存储或通过质量审核。"""

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
    """视频生成输入；时长单位为秒，宽高为像素。

    参考图和首尾帧是可选能力，不保证所有协议都会发送；未支持的输入、时长
    截断和实际提交参数应查看具体实现与结果 meta。
    """

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
    """视频结果或异步任务引用。

    content=None 允许表示尚无视频 bytes；task_ref 由远端服务定义。
    duration_seconds 是实现提供的时长元信息，不统一保证经过 ffprobe 实测。
    Provider 不在此保存资产，业务层负责选择版本、落库及确认正式完成状态。
    """

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
    """语音请求；speed 是服务定义的语速因子，audio_format 是请求编码格式。

    voice/style/language 与 provider_options 是否发送由具体协议决定。
    meta 可以开启实现专用的探测行为，调用前应确认其本地工具依赖。
    """

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
    """编码音频 bytes 与秒级时长；时长可能为估算值，来源应查看具体实现。"""

    content: bytes
    mime: str = "audio/wav"
    duration_seconds: float = 0.0
    provider: str = ""
    model_id: str = ""
    cost_usd: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


class BaseProvider(ABC):
    """配置驱动的模型能力实现，不负责 Session、业务审计或审批。

    options 由工厂合并供应商和模型配置。构造对象不等于接口已经可达或凭据有效。
    """

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
        """返回本实现声明的能力集合，不向远端探测。"""
        return {self.capability}

    def supports(self, capability: str) -> bool:
        """仅检查本地声明是否包含给定能力，不验证模型实际兼容性。"""
        return capability in self.capabilities

    @abstractmethod
    async def health(self) -> bool:  # pragma: no cover - trivial
        """执行实现约定的健康检查并返回布尔值。

        各实现可能只检查配置，也可能探测 HTTP；不能将本接口的 True 统一解释为
        鉴权、模型生成和媒体工具全部就绪。网络副作用及异常范围见具体实现。
        """
        raise NotImplementedError


class LLMProvider(BaseProvider):
    capability = "llm"

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResult:
        """按实现协议执行文字请求并返回 LLMResult。

        可能发生外部计费。错误类型、HTTP 超时及重试由实现说明；公共接口不自动
        执行 JSON Schema 业务校验、数据库写入、总 deadline 或任务取消。
        """
        raise NotImplementedError


class VisionProvider(BaseProvider):
    capability = "vision"

    @abstractmethod
    async def describe(self, request: VisionRequest) -> LLMResult:
        """按实现协议发送图像与文字并返回 LLMResult，业务层继续验证结构与内容。"""
        raise NotImplementedError


class ImageProvider(BaseProvider):
    capability = "image"

    @abstractmethod
    async def generate(self, request: ImageRequest) -> ImageResult:
        """请求图像并返回编码结果；存储、候选选择与审批由应用用例处理。"""
        raise NotImplementedError


class VideoProvider(BaseProvider):
    capability = "video"

    @abstractmethod
    async def generate(self, request: VideoRequest) -> VideoResult:
        """请求视频或异步任务；调用可能包含提交、轮询和下载等多次网络操作。

        返回与取消关系由实现说明，调用方不能只凭方法返回或超时判断远端任务状态。
        """
        raise NotImplementedError

    async def cancel(self, task_ref: str) -> bool:  # pragma: no cover - optional capability
        """尝试取消 task_ref 对应任务；默认返回 False，表示未实现该能力。

        具体实现的 True 也可能仅代表取消请求被接受，不统一证明远端已停止。
        """
        return False


class AudioProvider(BaseProvider):
    capability = "audio"

    @abstractmethod
    async def synthesize(self, request: AudioRequest) -> AudioResult:
        """按实现协议合成语音；可能使用本地时长探测，具体副作用见实现。"""
        raise NotImplementedError
