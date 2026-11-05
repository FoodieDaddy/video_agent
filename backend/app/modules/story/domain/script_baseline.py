"""剧本工作流基线指纹的纯领域规则。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_CONTENT_METADATA_KEYS = frozenset(
    {
        "id",
        "project_id",
        "version",
        "status",
        "approved",
        "approved_version",
        "agent_id",
        "model_id",
        "prompt_version",
        "config_version",
        "created_at",
        "updated_at",
        "workspace_meta",
    }
)


@dataclass(frozen=True, slots=True)
class ScriptFingerprintInput:
    """应用层投影后的不可变指纹输入，不暴露 ORM 或可变 JSON 对象。"""

    canonical_payload: bytes


def script_text_of_content(content: Mapping[str, Any] | None) -> str:
    """只读取正文文本；非字符串值视为空正文。"""
    value = (content or {}).get("script_text", "")
    return value if isinstance(value, str) else ""


def build_script_fingerprint_input(
    *,
    title: str,
    logline: str,
    synopsis: str,
    genre: str,
    tone: str,
    content: Mapping[str, Any] | None,
) -> ScriptFingerprintInput:
    """构造与旧指纹格式相同的规范化输入，保持已保存工作流基线可比较。"""
    content = content or {}
    business_content = {key: value for key, value in content.items() if key not in _CONTENT_METADATA_KEYS}
    payload = {
        "title": title,
        "logline": logline,
        "synopsis": synopsis,
        "genre": genre,
        "tone": tone,
        "script_text": script_text_of_content(content),
        "content": business_content,
    }
    canonical_payload = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return ScriptFingerprintInput(canonical_payload=canonical_payload)


def fingerprint_script(value: ScriptFingerprintInput) -> str:
    """返回剧本工作流基线指纹。"""
    return hashlib.sha256(value.canonical_payload).hexdigest()
