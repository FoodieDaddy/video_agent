"""Shared string constants / enums.

Keeping the vocabulary in one place makes task state transitions explicit and
prevents typo-driven bugs across agents, services and the API.
"""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    INGESTED = "ingested"
    SCRIPT_READY = "script_ready"
    CHARACTERS_READY = "characters_ready"
    STORYBOARD_READY = "storyboard_ready"
    VIDEO_READY = "video_ready"
    EDITED = "edited"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ShotStatus(StrEnum):
    DRAFT = "draft"
    PROMPT_READY = "prompt_ready"
    QUEUED = "queued"
    GENERATING = "generating"
    GENERATED = "generated"
    APPROVED = "approved"
    FAILED = "failed"


class CharacterStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    ARCHIVED = "archived"


class AssetKind(StrEnum):
    SOURCE_DOCUMENT = "source_document"
    REFERENCE_IMAGE = "reference_image"
    CHARACTER_IMAGE = "character_image"
    SCENE_IMAGE = "scene_image"
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    FILM = "film"
    EXPORT = "export"


class CharacterAssetKind(StrEnum):
    UPLOAD = "upload"
    PORTRAIT = "portrait"
    FULL_BODY = "full_body"
    TURNAROUND = "turnaround"
    EXPRESSION = "expression"
    COSTUME = "costume"
    SCENE_REFERENCE = "scene_reference"


class AudioKind(StrEnum):
    VOICE = "voice"
    NARRATION = "narration"
    MUSIC = "music"
    SFX = "sfx"


class EvaluationStage(StrEnum):
    CHARACTER = "character"
    STORYBOARD = "storyboard"
    SHOT = "shot"
    FINAL = "final"


class ReviewStage(StrEnum):
    CHARACTERS_SCENES = "characters_scenes"
    STORYBOARD = "storyboard"
    SHOTS = "shots"
    FINAL = "final"


DEFAULT_TIMELINE_FPS = 25
DEFAULT_VIDEO_WIDTH = 1280
DEFAULT_VIDEO_HEIGHT = 720
