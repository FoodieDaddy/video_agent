"""scenes 模块公开接口。

惰性导出避免启动时加载无关能力；内部实现仍由架构测试约束依赖方向。
"""

from importlib import import_module

_EXPORTS = {
    "list_scenes": ("app.modules.scenes.application.queries", "list_scenes"),
    "scene_profile_of": ("app.modules.scenes.application.queries", "scene_profile_of"),
    "scene_payload": ("app.modules.scenes.application.queries", "scene_payload"),
    "public_scene": ("app.modules.scenes.application.queries", "public_scene"),
    "update_scene": ("app.modules.scenes.application.use_cases", "update_scene"),
    "extract_scenes": ("app.modules.scenes.application.use_cases", "extract_scenes"),
    "describe_scenes": ("app.modules.scenes.application.use_cases", "describe_scenes"),
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
