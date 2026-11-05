"""Shared read helpers for production media application flows."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from studio_assets.public import asset_reference
from studio_platform.execution.runtime import AppRuntime
from studio_projects.contracts import ProjectContext as Project

logger = logging.getLogger(__name__)

_RESOLUTIONS = {
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "1:1": (1024, 1024),
    "4:3": (1024, 768),
}


def _output_dims(project: Project) -> tuple[int, int]:
    """根据项目设置与宽高比计算输出尺寸；无 I/O，不验证模型是否支持该尺寸。"""
    if project.aspect_ratio in _RESOLUTIONS:
        return _RESOLUTIONS[project.aspect_ratio]
    settings = project.settings or {}
    width = int(settings.get("width") or 1280)
    height = int(settings.get("height") or 720)
    return width, height


def _asset_bytes(runtime: AppRuntime, asset_id: str, db: Session) -> bytes | None:
    """按资产 ID 读取媒体字节；记录不存在返回 None，实际存储读取错误向上传播。"""
    asset = asset_reference(db, asset_id)
    if asset is None or not runtime.storage.exists(asset.storage_key):
        return None
    return runtime.read_media(asset.storage_key)
