"""应用组合根拥有业务输出 Schema 的装配清单。"""

from app.modules.ai_runtime.schema_registry import register_output_schemas
from app.modules.characters.contracts import (
    CharacterConsistencyOutput,
    CharacterExtractionOutput,
    CharacterProfileOutput,
    CharacterVisionOutput,
)
from app.modules.production.contracts import (
    AudioPlanOutput,
    DirectingPlanOutput,
    EditingPlanOutput,
    EvaluationReport,
    PromptPack,
    StoryboardOutput,
)
from app.modules.scenes.contracts import SceneExtractionOutput, SceneProfileOutput
from app.modules.story.contracts import ScriptOutput
from app.modules.workflow.contracts import OrchestratorPlan


def register_schemas() -> None:
    """正常启动和旧 Schema 导入共用同一次业务类型装配。"""
    register_output_schemas(
        {
            "script": ScriptOutput,
            "character_extraction": CharacterExtractionOutput,
            "character_profile": CharacterProfileOutput,
            "character_vision": CharacterVisionOutput,
            "character_consistency": CharacterConsistencyOutput,
            "scene_extraction": SceneExtractionOutput,
            "scene_profile": SceneProfileOutput,
            "directing_plan": DirectingPlanOutput,
            "storyboard": StoryboardOutput,
            "prompt_pack": PromptPack,
            "audio_plan": AudioPlanOutput,
            "editing_plan": EditingPlanOutput,
            "evaluation": EvaluationReport,
            "orchestrator_plan": OrchestratorPlan,
        },
        {
            "script": "script.schema.json",
            "character_extraction": "character.schema.json",
            "character_profile": "character_profile.schema.json",
            "scene_extraction": "scene.schema.json",
            "directing_plan": "directing_plan.schema.json",
            "storyboard": "storyboard.schema.json",
            "evaluation": "evaluation.schema.json",
        },
    )
