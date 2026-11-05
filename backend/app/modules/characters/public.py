"""characters 模块公开接口。

惰性导出避免启动时加载无关能力；内部实现仍由架构测试约束依赖方向。
"""

from importlib import import_module

_EXPORTS = {
    "list_character_snapshots": ("app.modules.characters.application.queries", "list_character_snapshots"),
    "find_character_reference": ("app.modules.characters.application.queries", "find_character_reference"),
    "approve_current_characters": (
        "app.modules.characters.application.approval",
        "approve_current_characters",
    ),
    "approve_character_profile": ("app.modules.characters.application.approval", "approve_character_profile"),
    "approve_character_entity": ("app.modules.characters.application.approval", "approve_character_entity"),
    "CHARACTER_ASSET_KINDS": ("app.modules.characters.application.assets", "CHARACTER_ASSET_KINDS"),
    "character_asset_public": ("app.modules.characters.application.assets", "character_asset_public"),
    "character_asset_version": ("app.modules.characters.application.assets", "character_asset_version"),
    "character_assets": ("app.modules.characters.application.assets", "character_assets"),
    "ensure_character_approved": ("app.modules.characters.application.assets", "ensure_character_approved"),
    "generate_character_assets": ("app.modules.characters.application.assets", "generate_character_assets"),
    "portrait_asset_id": ("app.modules.characters.application.queries", "portrait_asset_id"),
    "voice_reference": ("app.modules.characters.application.queries", "voice_reference"),
    "character_metrics": ("app.modules.characters.application.queries", "character_metrics"),
    "character_detail_reference_matches": (
        "app.modules.characters.application.queries",
        "character_detail_reference_matches",
    ),
    "list_characters": ("app.modules.characters.application.queries", "list_characters"),
    "profile_of": ("app.modules.characters.application.queries", "profile_of"),
    "character_payload": ("app.modules.characters.application.queries", "character_payload"),
    "public_character": ("app.modules.characters.application.queries", "public_character"),
    "update_character": ("app.modules.characters.application.use_cases", "update_character"),
    "extract_characters": ("app.modules.characters.application.use_cases", "extract_characters"),
    "describe_characters": ("app.modules.characters.application.use_cases", "describe_characters"),
    "CharacterImageInput": (
        "app.modules.characters.infrastructure.agents.character_image",
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
