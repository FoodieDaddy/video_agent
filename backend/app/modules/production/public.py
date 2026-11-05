"""production 模块公开接口。

惰性导出避免启动时加载无关能力；内部实现仍由架构测试约束依赖方向。
"""

from importlib import import_module

_EXPORTS = {
    "get_storyboard": ("app.modules.production.application.baselines", "get_storyboard"),
    "storyboard_source_status": ("app.modules.production.application.baselines", "storyboard_source_status"),
    "storyboard_review_snapshot": (
        "app.modules.production.application.baselines",
        "storyboard_review_snapshot",
    ),
    "assert_storyboard_review_snapshot": (
        "app.modules.production.application.baselines",
        "assert_storyboard_review_snapshot",
    ),
    "shot_edit_fingerprint": ("app.modules.production.application.fingerprints", "shot_edit_fingerprint"),
    "latest_plan": ("app.modules.production.application.queries", "latest_plan"),
    "get_directing_plan": ("app.modules.production.application.queries", "get_directing_plan"),
    "directing_source_status": ("app.modules.production.application.queries", "directing_source_status"),
    "latest_board": ("app.modules.production.application.queries", "latest_board"),
    "list_shots": ("app.modules.production.application.queries", "list_shots"),
    "shot_payload": ("app.modules.production.application.queries", "shot_payload"),
    "public_shot": ("app.modules.production.application.queries", "public_shot"),
    "project_summary": ("app.modules.production.application.queries", "project_summary"),
    "update_shot": ("app.modules.production.application.use_cases", "update_shot"),
    "build_directing_plan": ("app.modules.production.application.use_cases", "build_directing_plan"),
    "validate_directing_request": (
        "app.modules.production.application.use_cases",
        "validate_directing_request",
    ),
    "build_storyboard": ("app.modules.production.application.use_cases", "build_storyboard"),
    "validate_storyboard_request": (
        "app.modules.production.application.use_cases",
        "validate_storyboard_request",
    ),
    "refine_prompts": ("app.modules.production.application.use_cases", "refine_prompts"),
    "character_asset_version": ("app.modules.production.application.media", "character_asset_version"),
    "generate_character_assets": ("app.modules.production.application.media", "generate_character_assets"),
    "character_assets": ("app.modules.production.application.media", "character_assets"),
    "character_asset_public": ("app.modules.production.application.media", "character_asset_public"),
    "generate_shot_videos": ("app.modules.production.application.media", "generate_shot_videos"),
    "video_generations": ("app.modules.production.application.media", "video_generations"),
    "video_public": ("app.modules.production.application.media", "video_public"),
    "select_video": ("app.modules.production.application.media", "select_video"),
    "shot_start_times": ("app.modules.production.application.media", "shot_start_times"),
    "generate_audio": ("app.modules.production.application.media", "generate_audio"),
    "audio_tracks": ("app.modules.production.application.media", "audio_tracks"),
    "audio_public": ("app.modules.production.application.media", "audio_public"),
    "latest_editing": ("app.modules.production.application.media", "latest_editing"),
    "build_editing_plan": ("app.modules.production.application.media", "build_editing_plan"),
    "render_film": ("app.modules.production.application.media", "render_film"),
    "export_film": ("app.modules.production.application.media", "export_film"),
    "editing_public": ("app.modules.production.application.media", "editing_public"),
    "latest_film_asset": ("app.modules.production.application.media", "latest_film_asset"),
    "ensure_character_approved": ("app.modules.production.application.media", "ensure_character_approved"),
    "collect_metrics": ("app.modules.production.application.quality", "collect_metrics"),
    "evaluate_project": ("app.modules.production.application.quality", "evaluate_project"),
    "latest_evaluation": ("app.modules.production.application.quality", "latest_evaluation"),
    "evaluation_public": ("app.modules.production.application.quality", "evaluation_public"),
    "CHARACTER_ASSET_KINDS": ("app.modules.production.application.media", "CHARACTER_ASSET_KINDS"),
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
