"""应用组合根聚合全部 ORM 映射，保证唯一 metadata 完整注册。"""

from app.modules.ai_runtime.infrastructure.persistence.models import AgentRun, BudgetEvent, ModelCallLog
from app.modules.assets.infrastructure.persistence.models import Asset, AssetVersion
from app.modules.characters.infrastructure.persistence.models import (
    Character,
    CharacterAsset,
    CharacterCostume,
    CharacterProfile,
    CharacterRelationship,
    CharacterState,
    CharacterVoice,
)
from app.modules.configuration.infrastructure.persistence.models import ConfigVersion, PromptVersion
from app.modules.platform.persistence.base import Base
from app.modules.platform.persistence.models import Task, TaskEvent
from app.modules.production.infrastructure.persistence.models import (
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
from app.modules.projects.infrastructure.persistence.models import Project, ProjectMember, User
from app.modules.reviews.infrastructure.persistence.models import Review, ReviewComment
from app.modules.scenes.infrastructure.persistence.models import Scene, SceneAsset, SceneProfile
from app.modules.story.infrastructure.persistence.models import (
    Script,
    SourceDocument,
    StoryChapter,
    StoryEvent,
)
from app.modules.workflow.infrastructure.persistence.models import WorkflowCheckpoint, WorkflowRun

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
