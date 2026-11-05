"""人物领域 Agent 的模块内注册表。"""

from studio_ai_runtime.base import BaseAgent

from .character_consistency import CharacterConsistencyAgent
from .character_description import CharacterDescriptionAgent
from .character_extraction import CharacterExtractionAgent
from .character_image import CharacterImageAgent
from .character_vision import CharacterVisionAgent

AGENTS: dict[str, type[BaseAgent]] = {
    "character_extraction": CharacterExtractionAgent,
    "character_description": CharacterDescriptionAgent,
    "character_vision": CharacterVisionAgent,
    "character_image": CharacterImageAgent,
    "character_consistency": CharacterConsistencyAgent,
}
