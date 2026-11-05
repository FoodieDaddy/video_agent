"""production 模块公开接口。

惰性导出避免启动时加载无关能力；内部实现仍由架构测试约束依赖方向。
"""

from importlib import import_module

_EXPORTS = {
    "generate_shot_video_by_id": ("studio_production.application.commands", "generate_shot_video_by_id"),
    "latest_film_reference": ("studio_production.application.editing", "latest_film_reference"),
    "approve_storyboard_targets": (
        "studio_production.application.approval",
        "approve_storyboard_targets",
    ),
    "approve_current_shots": ("studio_production.application.approval", "approve_current_shots"),
    "approve_shot_selection": ("studio_production.application.approval", "approve_shot_selection"),
    "approve_shot_entity": ("studio_production.application.approval", "approve_shot_entity"),
    "approve_latest_render": ("studio_production.application.approval", "approve_latest_render"),
    "prepare_storyboard_review_snapshot": (
        "studio_production.application.baselines",
        "prepare_storyboard_review_snapshot",
    ),
    "assert_storyboard_approval_targets": (
        "studio_production.application.baselines",
        "assert_storyboard_approval_targets",
    ),
    "get_storyboard": ("studio_production.application.baselines", "get_storyboard"),
    "storyboard_source_status": ("studio_production.application.baselines", "storyboard_source_status"),
    "storyboard_review_snapshot": (
        "studio_production.application.baselines",
        "storyboard_review_snapshot",
    ),
    "assert_storyboard_review_snapshot": (
        "studio_production.application.baselines",
        "assert_storyboard_review_snapshot",
    ),
    "shot_edit_fingerprint": ("studio_production.application.fingerprints", "shot_edit_fingerprint"),
    "latest_plan": ("studio_production.application.queries", "latest_plan"),
    "get_directing_plan": ("studio_production.application.queries", "get_directing_plan"),
    "directing_source_status": ("studio_production.application.queries", "directing_source_status"),
    "latest_board": ("studio_production.application.queries", "latest_board"),
    "list_shots": ("studio_production.application.queries", "list_shots"),
    "shot_payload": ("studio_production.application.queries", "shot_payload"),
    "public_shot": ("studio_production.application.queries", "public_shot"),
    "project_summary": ("studio_production.application.queries", "project_summary"),
    "update_shot": ("studio_production.application.use_cases", "update_shot"),
    "build_directing_plan": ("studio_production.application.use_cases", "build_directing_plan"),
    "validate_directing_request": (
        "studio_production.application.use_cases",
        "validate_directing_request",
    ),
    "build_storyboard": ("studio_production.application.use_cases", "build_storyboard"),
    "validate_storyboard_request": (
        "studio_production.application.use_cases",
        "validate_storyboard_request",
    ),
    "refine_prompts": ("studio_production.application.use_cases", "refine_prompts"),
    "character_asset_version": (
        "studio_characters.public",
        "character_asset_version",
    ),
    "generate_character_assets": (
        "studio_characters.public",
        "generate_character_assets",
    ),
    "character_assets": ("studio_characters.public", "character_assets"),
    "character_asset_public": (
        "studio_characters.public",
        "character_asset_public",
    ),
    "generate_shot_videos": ("studio_production.application.shot_video", "generate_shot_videos"),
    "video_generations": ("studio_production.application.shot_video", "video_generations"),
    "video_public": ("studio_production.application.shot_video", "video_public"),
    "select_video": ("studio_production.application.shot_video", "select_video"),
    "shot_start_times": ("studio_production.application.audio", "shot_start_times"),
    "generate_audio": ("studio_production.application.audio", "generate_audio"),
    "audio_tracks": ("studio_production.application.audio", "audio_tracks"),
    "audio_public": ("studio_production.application.audio", "audio_public"),
    "latest_editing": ("studio_production.application.editing", "latest_editing"),
    "build_editing_plan": ("studio_production.application.editing", "build_editing_plan"),
    "render_film": ("studio_production.application.editing", "render_film"),
    "export_film": ("studio_production.application.editing", "export_film"),
    "editing_public": ("studio_production.application.editing", "editing_public"),
    "latest_film_asset": ("studio_production.application.editing", "latest_film_asset"),
    "ensure_character_approved": (
        "studio_characters.public",
        "ensure_character_approved",
    ),
    "collect_metrics": ("studio_production.application.quality", "collect_metrics"),
    "evaluate_project": ("studio_production.application.quality", "evaluate_project"),
    "latest_evaluation": ("studio_production.application.quality", "latest_evaluation"),
    "evaluation_public": ("studio_production.application.quality", "evaluation_public"),
    "CHARACTER_ASSET_KINDS": (
        "studio_characters.public",
        "CHARACTER_ASSET_KINDS",
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
