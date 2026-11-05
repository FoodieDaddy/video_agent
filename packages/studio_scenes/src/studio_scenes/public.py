"""scenes 模块公开接口。

惰性导出避免启动时加载无关能力；内部实现仍由架构测试约束依赖方向。
"""

from importlib import import_module

_EXPORTS = {
    "list_scene_snapshots": ("studio_scenes.application.queries", "list_scene_snapshots"),
    "approve_current_scenes": ("studio_scenes.application.approval", "approve_current_scenes"),
    "approve_scene_profile": ("studio_scenes.application.approval", "approve_scene_profile"),
    "approve_scene_entity": ("studio_scenes.application.approval", "approve_scene_entity"),
    "list_scenes": ("studio_scenes.application.queries", "list_scenes"),
    "scene_profile_of": ("studio_scenes.application.queries", "scene_profile_of"),
    "scene_payload": ("studio_scenes.application.queries", "scene_payload"),
    "public_scene": ("studio_scenes.application.queries", "public_scene"),
    "update_scene": ("studio_scenes.application.use_cases", "update_scene"),
    "extract_scenes": ("studio_scenes.application.use_cases", "extract_scenes"),
    "describe_scenes": ("studio_scenes.application.use_cases", "describe_scenes"),
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
