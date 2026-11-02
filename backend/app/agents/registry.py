"""Agent registry: id → implementation.

Business code (services, workflow engine) obtains agents from here, so adding an
agent means registering a class and dropping a YAML file in ``config/agents``.
"""

from __future__ import annotations

from app.agents.audio import AudioAgent, AudioVoiceAgent
from app.agents.base import BaseAgent
from app.agents.character_consistency import CharacterConsistencyAgent
from app.agents.character_description import CharacterDescriptionAgent
from app.agents.character_extraction import CharacterExtractionAgent
from app.agents.character_image import CharacterImageAgent
from app.agents.character_vision import CharacterVisionAgent
from app.agents.director import DirectorAgent
from app.agents.editing import EditingAgent
from app.agents.evaluation import EvaluationAgent
from app.agents.orchestrator import OrchestratorAgent
from app.agents.prompt import PromptAgent
from app.agents.scene import SceneDescriptionAgent, SceneExtractionAgent
from app.agents.script import ScriptAgent
from app.agents.storyboard import StoryboardAgent
from app.agents.video import VideoAgent
from app.core.config_store import ConfigStore
from app.core.exceptions import ConfigurationError

AGENT_CLASSES: dict[str, type[BaseAgent]] = {
    "orchestrator": OrchestratorAgent,
    "script": ScriptAgent,
    "character_extraction": CharacterExtractionAgent,
    "character_description": CharacterDescriptionAgent,
    "character_vision": CharacterVisionAgent,
    "character_image": CharacterImageAgent,
    "character_consistency": CharacterConsistencyAgent,
    "scene_extraction": SceneExtractionAgent,
    "scene_description": SceneDescriptionAgent,
    "director": DirectorAgent,
    "storyboard": StoryboardAgent,
    "prompt": PromptAgent,
    "video": VideoAgent,
    "audio": AudioAgent,
    "audio_voice": AudioVoiceAgent,
    "editing": EditingAgent,
    "evaluation": EvaluationAgent,
}


def agent_ids() -> list[str]:
    return sorted(AGENT_CLASSES)


def create_agent(agent_id: str, config_store: ConfigStore) -> BaseAgent:
    cls = AGENT_CLASSES.get(agent_id)
    if cls is None:
        raise ConfigurationError(f"Unknown agent type '{agent_id}'")
    return cls(config_store)


def describe_agents(config_store: ConfigStore) -> list[dict]:
    """Registry view used by the admin API."""
    described: list[dict] = []
    for agent_id in agent_ids():
        config = config_store.try_agent(agent_id)
        described.append(
            {
                "id": agent_id,
                "class": AGENT_CLASSES[agent_id].__name__,
                "capability": AGENT_CLASSES[agent_id].capability,
                "configured": config is not None,
                "enabled": bool(config and config.enabled),
                "provider": config.model.provider if config else "",
                "model_id": config.model.model_id if config else "",
                "config_version": config.config_version if config else "",
            }
        )
    return described
