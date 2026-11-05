"""characters 模块公开接口。

惰性导出避免启动时加载无关能力；内部实现仍由架构测试约束依赖方向。
"""

from importlib import import_module

_EXPORTS = {
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
