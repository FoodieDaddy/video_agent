"""视频制作领域 Agent 的模块内注册表。"""

from studio_ai_runtime.base import BaseAgent

from .audio import AudioAgent, AudioVoiceAgent
from .director import DirectorAgent
from .editing import EditingAgent
from .evaluation import EvaluationAgent
from .prompt import PromptAgent
from .storyboard import StoryboardAgent
from .video import VideoAgent

AGENTS: dict[str, type[BaseAgent]] = {
    "director": DirectorAgent,
    "storyboard": StoryboardAgent,
    "prompt": PromptAgent,
    "video": VideoAgent,
    "audio": AudioAgent,
    "audio_voice": AudioVoiceAgent,
    "editing": EditingAgent,
    "evaluation": EvaluationAgent,
}
