"""应用组合根聚合全部 ORM 映射，保证唯一 metadata 完整注册。"""

from studio_ai_runtime.infrastructure.persistence.models import AgentRun, BudgetEvent, ModelCallLog
from studio_assets.infrastructure.persistence.models import Asset, AssetVersion
from studio_characters.infrastructure.persistence.models import (
    Character,
    CharacterAsset,
    CharacterCostume,
    CharacterProfile,
    CharacterRelationship,
    CharacterState,
    CharacterVoice,
)
from studio_configuration.infrastructure.persistence.models import ConfigVersion, PromptVersion
from studio_platform.persistence.base import Base
from studio_platform.persistence.models import Task, TaskEvent
from studio_production.infrastructure.persistence.models import (
    AudioTrack,
    DirectingPlan,
    EditingProject,
    EvaluationResult,
    EvaluationRun,
    Shot,
    ShotCharacter,
    Storyboard,
    VideoGeneration,
)
from studio_projects.infrastructure.persistence.models import Project, ProjectMember, User
from studio_reviews.infrastructure.persistence.models import Review, ReviewComment
from studio_scenes.infrastructure.persistence.models import Scene, SceneAsset, SceneProfile
from studio_story.infrastructure.persistence.models import (
    Script,
    SourceDocument,
    StoryChapter,
    StoryEvent,
)
from studio_workflow.infrastructure.persistence.models import WorkflowCheckpoint, WorkflowRun

__all__ = [
    "AgentRun",
    "Asset",
    "AssetVersion",
    "AudioTrack",
    "Base",
    "BudgetEvent",
    "Character",
    "CharacterAsset",
    "CharacterCostume",
    "CharacterProfile",
    "CharacterRelationship",
    "CharacterState",
    "CharacterVoice",
    "ConfigVersion",
    "DirectingPlan",
    "EditingProject",
    "EvaluationResult",
    "EvaluationRun",
    "ModelCallLog",
    "Project",
    "ProjectMember",
    "PromptVersion",
    "Review",
    "ReviewComment",
    "Scene",
    "SceneAsset",
    "SceneProfile",
    "Script",
    "Shot",
    "ShotCharacter",
    "SourceDocument",
    "Storyboard",
    "StoryChapter",
    "StoryEvent",
    "Task",
    "TaskEvent",
    "User",
    "VideoGeneration",
    "WorkflowCheckpoint",
    "WorkflowRun",
]


def register_models() -> None:
    """导入本模块即完成映射注册；重复调用不创建新表定义。"""
