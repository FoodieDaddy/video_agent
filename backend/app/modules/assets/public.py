"""assets 模块公开入口；跨模块调用仅依赖此处声明的操作。"""

from app.modules.assets.application.service import (
    asset_public,
    asset_url,
    build_key,
    list_assets,
    local_path,
    read_asset,
    record_asset_version,
    save_asset,
)

__all__ = [
    "build_key",
    "save_asset",
    "record_asset_version",
    "list_assets",
    "asset_url",
    "read_asset",
    "local_path",
    "asset_public",
]
