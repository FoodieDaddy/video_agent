"""旧 pipeline 兼容 模块公开接口。

惰性导出避免启动时加载无关能力；内部实现仍由架构测试约束依赖方向。
"""

from importlib import import_module

_EXPORTS = {
    "latest_script": ("app.modules.story.application.queries", "latest_script"),
    "script_payload": ("app.modules.story.application.queries", "script_payload"),
    "_latest_document_id": ("app.modules.story.application.queries", "_latest_document_id"),
    "update_script": ("app.modules.story.application.use_cases", "update_script"),
    "generate_script": ("app.modules.story.application.use_cases", "generate_script"),
    "list_characters": ("app.modules.characters.application.queries", "list_characters"),
    "profile_of": ("app.modules.characters.application.queries", "profile_of"),
    "character_payload": ("app.modules.characters.application.queries", "character_payload"),
    "public_character": ("app.modules.characters.application.queries", "public_character"),
    "_profile_version": ("app.modules.characters.application.queries", "_profile_version"),
    "update_character": ("app.modules.characters.application.use_cases", "update_character"),
    "extract_characters": ("app.modules.characters.application.use_cases", "extract_characters"),
    "describe_characters": ("app.modules.characters.application.use_cases", "describe_characters"),
    "list_scenes": ("app.modules.scenes.application.queries", "list_scenes"),
    "scene_profile_of": ("app.modules.scenes.application.queries", "scene_profile_of"),
    "scene_payload": ("app.modules.scenes.application.queries", "scene_payload"),
    "public_scene": ("app.modules.scenes.application.queries", "public_scene"),
    "update_scene": ("app.modules.scenes.application.use_cases", "update_scene"),
    "extract_scenes": ("app.modules.scenes.application.use_cases", "extract_scenes"),
    "describe_scenes": ("app.modules.scenes.application.use_cases", "describe_scenes"),
    "latest_plan": ("app.modules.production.application.queries", "latest_plan"),
    "latest_board": ("app.modules.production.application.queries", "latest_board"),
    "list_shots": ("app.modules.production.application.queries", "list_shots"),
    "shot_payload": ("app.modules.production.application.queries", "shot_payload"),
    "public_shot": ("app.modules.production.application.queries", "public_shot"),
    "project_summary": ("app.modules.production.application.queries", "project_summary"),
    "update_shot": ("app.modules.production.application.use_cases", "update_shot"),
    "build_directing_plan": ("app.modules.production.application.use_cases", "build_directing_plan"),
    "build_storyboard": ("app.modules.production.application.use_cases", "build_storyboard"),
    "refine_prompts": ("app.modules.production.application.use_cases", "refine_prompts"),
    "_next_version": ("app.modules.platform.persistence.versions", "next_version"),
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
