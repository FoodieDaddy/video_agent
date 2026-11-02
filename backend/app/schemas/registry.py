"""Schema registry.

Every agent output schema is registered here so that:

* providers get a JSON schema to constrain structured output,
* the API/test suite can validate payloads,
* ``config/schemas/*.schema.json`` can be regenerated from a single source.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.schemas.audio import AudioPlanOutput
from app.schemas.character import (
    CharacterConsistencyOutput,
    CharacterExtractionOutput,
    CharacterProfileOutput,
    CharacterVisionOutput,
)
from app.schemas.director import DirectingPlanOutput
from app.schemas.editing import EditingPlanOutput
from app.schemas.evaluation import EvaluationReport
from app.schemas.orchestrator import OrchestratorPlan
from app.schemas.prompt import PromptPack
from app.schemas.scene import SceneExtractionOutput, SceneProfileOutput
from app.schemas.script import ScriptOutput
from app.schemas.storyboard import StoryboardOutput

OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {
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
}

# File names shipped under ``config/schemas`` (a stable, reviewable subset).
SCHEMA_FILES = {
    "script": "script.schema.json",
    "character_extraction": "character.schema.json",
    "character_profile": "character_profile.schema.json",
    "scene_extraction": "scene.schema.json",
    "storyboard": "storyboard.schema.json",
    "evaluation": "evaluation.schema.json",
}


def schema_for(name: str) -> type[BaseModel]:
    try:
        return OUTPUT_SCHEMAS[name]
    except KeyError as exc:
        raise KeyError(f"Unknown output schema '{name}'") from exc


def json_schema(name: str) -> dict[str, Any]:
    return schema_for(name).model_json_schema()


def export_schemas(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, filename in SCHEMA_FILES.items():
        target = directory / filename
        target.write_text(
            json.dumps(json_schema(name), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(target)
    return written
