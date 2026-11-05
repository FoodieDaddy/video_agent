"""通用 Schema 注册机制；具体业务类型与导出文件由应用组合根提供。"""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any

from pydantic import BaseModel

OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {}
SCHEMA_FILES: dict[str, str] = {}
_registration_lock = RLock()


def register_output_schemas(schemas: dict[str, type[BaseModel]], filenames: dict[str, str]) -> None:
    """注册业务输出与导出名；同一对象可重复装配，冲突先拒绝后写入。"""
    with _registration_lock:
        for name, schema in schemas.items():
            if name in OUTPUT_SCHEMAS and OUTPUT_SCHEMAS[name] is not schema:
                raise ValueError(f"Output schema '{name}' is already registered")
        for name, filename in filenames.items():
            if name not in schemas and name not in OUTPUT_SCHEMAS:
                raise ValueError(f"Cannot export unregistered output schema '{name}'")
            if name in SCHEMA_FILES and SCHEMA_FILES[name] != filename:
                raise ValueError(f"Output schema '{name}' already has another export filename")
            if Path(filename).name != filename or filename in {"", ".", ".."}:
                raise ValueError(f"Invalid schema export filename '{filename}'")
        OUTPUT_SCHEMAS.update(schemas)
        SCHEMA_FILES.update(filenames)


def schema_for(name: str) -> type[BaseModel]:
    """读取已装配 Schema；未知名字沿用旧 KeyError 语义。"""
    try:
        return OUTPUT_SCHEMAS[name]
    except KeyError as exc:
        raise KeyError(f"Unknown output schema '{name}'") from exc


def json_schema(name: str) -> dict[str, Any]:
    return schema_for(name).model_json_schema()


def export_schemas(directory: Path) -> list[Path]:
    """导出组合根声明的稳定子集，不在 runtime 中静态导入业务模块。"""
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, filename in SCHEMA_FILES.items():
        target = directory / filename
        target.write_text(
            json.dumps(json_schema(name), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(target)
    return written
