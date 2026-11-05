"""characters 模块公开接口。

惰性导出避免启动时加载无关能力；内部实现仍由架构测试约束依赖方向。
"""

from importlib import import_module

_EXPORTS = {
    "list_character_snapshots": ("studio_characters.application.queries", "list_character_snapshots"),
    "find_character_reference": ("studio_characters.application.queries", "find_character_reference"),
    "approve_current_characters": (
        "studio_characters.application.approval",
        "approve_current_characters",
    ),
    "approve_character_profile": ("studio_characters.application.approval", "approve_character_profile"),
    "approve_character_entity": ("studio_characters.application.approval", "approve_character_entity"),
    "CHARACTER_ASSET_KINDS": ("studio_characters.application.assets", "CHARACTER_ASSET_KINDS"),
    "character_asset_public": ("studio_characters.application.assets", "character_asset_public"),
    "character_asset_version": ("studio_characters.application.assets", "character_asset_version"),
    "character_assets": ("studio_characters.application.assets", "character_assets"),
    "ensure_character_approved": ("studio_characters.application.assets", "ensure_character_approved"),
    "generate_character_assets": ("studio_characters.application.assets", "generate_character_assets"),
    "portrait_asset_id": ("studio_characters.application.queries", "portrait_asset_id"),
    "voice_reference": ("studio_characters.application.queries", "voice_reference"),
    "character_metrics": ("studio_characters.application.queries", "character_metrics"),
    "character_detail_reference_matches": (
        "studio_characters.application.queries",
        "character_detail_reference_matches",
    ),
    "list_characters": ("studio_characters.application.queries", "list_characters"),
    "profile_of": ("studio_characters.application.queries", "profile_of"),
    "character_payload": ("studio_characters.application.queries", "character_payload"),
    "public_character": ("studio_characters.application.queries", "public_character"),
    "update_character": ("studio_characters.application.use_cases", "update_character"),
    "extract_characters": ("studio_characters.application.use_cases", "extract_characters"),
    "describe_characters": ("studio_characters.application.use_cases", "describe_characters"),
    "CharacterImageInput": (
        "studio_characters.infrastructure.agents.character_image",
        "CharacterImageInput",
    ),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name):
    try:
        module, attribute = _EXPORTS[name]
    except KeyError:
        raise AttributeError(name) from None
    return getattr(import_module(module), attribute)


def __dir__():
    return sorted(set(globals()) | set(__all__))
