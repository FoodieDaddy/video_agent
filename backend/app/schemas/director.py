"""导演规划契约：保留旧输出字段，显式拒绝空风格和非法镜头策略。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ShotStrategy(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # 未提供时沿用旧协议默认值；显式的零、负数或非有限时长不由后处理补成成功。
    total_shots: int = Field(default=6, ge=1, le=120)
    avg_duration_seconds: float = Field(default=5.0, gt=0, allow_inf_nan=False)
    pacing_notes: str = ""
    coverage_notes: str = ""


class DirectingPlanInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    script: dict = Field(default_factory=dict)
    characters: list[dict] = Field(default_factory=list)
    scenes: list[dict] = Field(default_factory=list)
    genre: str = ""
    shots_target: int = Field(default=6, ge=1, le=120)
    instruction: str = Field(default="", max_length=8000)


class DirectingPlanOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    visual_style: str = Field(min_length=1, pattern=r"\S")
    color_palette: list[str] = Field(default_factory=list)
    lighting_style: str = ""
    camera_language: str = ""
    pacing: str = ""
    narrative_arc: str = ""
    shot_strategy: ShotStrategy = Field(default_factory=ShotStrategy)
    continuity_rules: list[str] = Field(default_factory=list)
    scenes_order: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("visual_style", mode="before")
    @classmethod
    def strip_visual_style(cls, value):
        """视觉风格必须由模型真实提供，不能让空白字符串绕过最小长度校验。"""
        return value.strip() if isinstance(value, str) else value
