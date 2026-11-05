"""跨模块资产引用契约，不携带数据库会话或 ORM 行。"""

from dataclasses import dataclass
from typing import Any, Protocol


class LegacyAssetRecord(Protocol):
    """旧成片接口的结构类型；仅用于描述兼容返回，不承诺脱离 Session。"""

    id: str
    project_id: str
    kind: str
    storage_key: str
    mime_type: str
    size_bytes: int
    width: int | None
    height: int | None
    duration_seconds: float | None
    model_id: str
    prompt_version: str
    config_version: str
    meta: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AssetReference:
    """已保存资产的只读引用；尺寸与时长未知时保持 None。"""

    asset_id: str
    project_id: str
    kind: str
    storage_key: str
    mime_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None


__all__ = ["AssetReference", "LegacyAssetRecord"]
