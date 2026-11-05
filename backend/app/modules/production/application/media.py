"""Compatibility re-exports for the former production media application module."""

from app.modules.production.application.audio import (
    _dialogue_lines_from_shots,
    _voice_for,
    _write_subtitles,
    audio_public,
    audio_tracks,
    generate_audio,
    shot_start_times,
)
from app.modules.production.application.character_assets import (
    CHARACTER_ASSET_KINDS,
    character_asset_public,
    character_asset_version,
    character_assets,
    ensure_character_approved,
    generate_character_assets,
)
from app.modules.production.application.editing import (
    _clip_audio,
    _clip_source,
    build_editing_plan,
    editing_public,
    export_film,
    latest_editing,
    latest_film_asset,
    render_film,
)
from app.modules.production.application.media_support import _RESOLUTIONS, _asset_bytes, _output_dims
from app.modules.production.application.shot_video import (
    _shot_reference,
    _video_version,
    generate_shot_videos,
    select_video,
    video_generations,
    video_public,
)

__all__ = [
    "CHARACTER_ASSET_KINDS",
    "_RESOLUTIONS",
    "_asset_bytes",
    "_clip_audio",
    "_clip_source",
    "_dialogue_lines_from_shots",
    "_output_dims",
    "_shot_reference",
    "_video_version",
    "_voice_for",
    "_write_subtitles",
    "audio_public",
    "audio_tracks",
    "build_editing_plan",
    "character_asset_public",
    "character_asset_version",
    "character_assets",
    "editing_public",
    "ensure_character_approved",
    "export_film",
    "generate_audio",
    "generate_character_assets",
    "generate_shot_videos",
    "latest_editing",
    "latest_film_asset",
    "render_film",
    "select_video",
    "shot_start_times",
    "video_generations",
    "video_public",
]
