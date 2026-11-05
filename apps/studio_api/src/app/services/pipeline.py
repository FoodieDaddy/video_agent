"""旧 pipeline 兼容 模块公开接口。

惰性导出避免启动时加载无关能力；内部实现仍由架构测试约束依赖方向。
"""

from importlib import import_module

_EXPORTS = {
    "latest_script": ("studio_story.application.queries", "latest_script"),
    "script_payload": ("studio_story.application.queries", "script_payload"),
    "_latest_document_id": ("studio_story.application.queries", "_latest_document_id"),
    "update_script": ("studio_story.application.use_cases", "update_script"),
    "generate_script": ("studio_story.application.use_cases", "generate_script"),
    "list_characters": ("studio_characters.application.queries", "list_characters"),
    "profile_of": ("studio_characters.application.queries", "profile_of"),
    "character_payload": ("studio_characters.application.queries", "character_payload"),
    "public_character": ("studio_characters.application.queries", "public_character"),
    "_profile_version": ("studio_characters.application.queries", "_profile_version"),
    "update_character": ("studio_characters.application.use_cases", "update_character"),
    "extract_characters": ("studio_characters.application.use_cases", "extract_characters"),
    "describe_characters": ("studio_characters.application.use_cases", "describe_characters"),
    "list_scenes": ("studio_scenes.application.queries", "list_scenes"),
    "scene_profile_of": ("studio_scenes.application.queries", "scene_profile_of"),
    "scene_payload": ("studio_scenes.application.queries", "scene_payload"),
    "public_scene": ("studio_scenes.application.queries", "public_scene"),
    "update_scene": ("studio_scenes.application.use_cases", "update_scene"),
    "extract_scenes": ("studio_scenes.application.use_cases", "extract_scenes"),
    "describe_scenes": ("studio_scenes.application.use_cases", "describe_scenes"),
    "latest_plan": ("studio_production.application.queries", "latest_plan"),
    "latest_board": ("studio_production.application.queries", "latest_board"),
    "list_shots": ("studio_production.application.queries", "list_shots"),
    "shot_payload": ("studio_production.application.queries", "shot_payload"),
    "public_shot": ("studio_production.application.queries", "public_shot"),
    "project_summary": ("studio_production.application.queries", "project_summary"),
    "update_shot": ("studio_production.application.use_cases", "update_shot"),
    "build_directing_plan": ("studio_production.application.use_cases", "build_directing_plan"),
    "build_storyboard": ("studio_production.application.use_cases", "build_storyboard"),
    "refine_prompts": ("studio_production.application.use_cases", "refine_prompts"),
    "_next_version": ("studio_platform.persistence.versions", "next_version"),
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
