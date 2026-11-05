"""旧制作模块人物资产入口；实现和写入所有权归 characters 模块。"""

from app.modules.characters.public import (
    CHARACTER_ASSET_KINDS,
    character_asset_public,
    character_asset_version,
    character_assets,
    ensure_character_approved,
    generate_character_assets,
)

__all__ = [
    "CHARACTER_ASSET_KINDS",
    "character_asset_public",
    "character_asset_version",
    "character_assets",
    "ensure_character_approved",
    "generate_character_assets",
]
