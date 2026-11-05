"""纯序列化契约；不依赖业务模块、SQLAlchemy 或 AI 执行器。

保持原调用审计中的 bytes 摘要和媒体输出 content 排除规则，供任务基础设施
与 Agent 执行协调共同使用，避免两者为序列化互相依赖。
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any, cast

from pydantic import BaseModel


def json_safe(value: Any) -> Any:
    """将输入输出转换为可写入 JSON 列的数据，本函数不访问数据库。

    bytes 仅记录长度摘要；模型、数据类和容器递归转换，其他非 JSON 对象
    字符串化。保持原有审计序列化规则，不将二进制内容复制到记录中。
    """
    if isinstance(value, BaseModel):
        # 先使用 Python 模式导出，JSON 模式无法直接编码原始 bytes。
        return json_safe(value.model_dump())
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return json_safe(dataclasses.asdict(value))
    if isinstance(value, bytes):
        return {"__bytes__": len(value)}
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def serialize_output(output: Any) -> dict[str, Any]:
    """转换执行结果；数据类输出排除 content，模型输出继续递归转换。"""
    if isinstance(output, BaseModel):
        return cast(dict[str, Any], json_safe(output.model_dump()))
    if dataclasses.is_dataclass(output) and not isinstance(output, type):
        payload = dataclasses.asdict(output)
        payload.pop("content", None)  # 数据类的二进制 content 不复制到审计记录。
        return cast(dict[str, Any], json_safe(payload))
    return {"value": json_safe(output)}


def dumps(value: Any) -> str:
    return json.dumps(json_safe(value), ensure_ascii=False)
