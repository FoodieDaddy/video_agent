"""production 模块的公开数据契约；重新导出现有类型，保持 Schema 单一来源。"""

from dataclasses import dataclass

from app.modules.production.schemas.audio import AudioPlanInput, AudioPlanOutput, VoiceLineDraft
from app.modules.production.schemas.director import DirectingPlanInput, DirectingPlanOutput, ShotStrategy
from app.modules.production.schemas.editing import EditingPlanInput, EditingPlanOutput, TimelineClip
from app.modules.production.schemas.evaluation import EvaluationInput, EvaluationIssue, EvaluationReport
from app.modules.production.schemas.prompt import PromptInput, PromptPack
from app.modules.production.schemas.storyboard import (
    CameraSpec,
    ShotCharacterRef,
    ShotDialogue,
    ShotDraft,
    StoryboardInput,
    StoryboardOutput,
)
from app.modules.production.schemas.video import ShotVideoInput, ShotVideoOutput


@dataclass(frozen=True, slots=True)
class StoryboardApprovalTargets:
    """本事务核验过的分镜批准目标，仅携带稳定 ID。"""

    project_id: str
    storyboard_id: str
    directing_plan_id: str
    shot_ids: tuple[str, ...]


__all__ = [
    "AudioPlanInput",
    "AudioPlanOutput",
    "CameraSpec",
    "DirectingPlanInput",
    "DirectingPlanOutput",
    "EditingPlanInput",
    "EditingPlanOutput",
    "EvaluationInput",
    "EvaluationIssue",
    "EvaluationReport",
    "PromptInput",
    "PromptPack",
    "ShotCharacterRef",
    "ShotDialogue",
    "ShotDraft",
    "ShotStrategy",
    "ShotVideoInput",
    "ShotVideoOutput",
    "StoryboardInput",
    "StoryboardOutput",
    "StoryboardApprovalTargets",
    "TimelineClip",
    "VoiceLineDraft",
]
