"""导演输入输出契约回归：本地校验与模板渲染，不访问模型或正式数据库。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.ai_runtime.base import AgentContext
from app.modules.platform.configuration.config_store import ConfigStore
from app.modules.production.infrastructure.agents.director import DirectorAgent
from app.schemas.director import DirectingPlanInput, DirectingPlanOutput, ShotStrategy


@pytest.fixture()
def agent(settings):
    return DirectorAgent(ConfigStore(settings))


@pytest.mark.parametrize("style", ["", " \n\t "])
def test_empty_visual_style_is_not_accepted_as_a_generic_plan(style):
    with pytest.raises(ValidationError):
        DirectingPlanOutput(visual_style=style)


@pytest.mark.parametrize("count", [0, -1, 121])
def test_explicit_invalid_shot_counts_are_rejected(count):
    with pytest.raises(ValidationError):
        ShotStrategy(total_shots=count)
    with pytest.raises(ValidationError):
        DirectingPlanInput(shots_target=count)


@pytest.mark.parametrize("duration", [0, -0.1, float("nan"), float("inf"), -float("inf")])
def test_durations_must_be_positive_and_finite(duration):
    with pytest.raises(ValidationError):
        ShotStrategy(avg_duration_seconds=duration)


def test_legacy_defaults_remain_available_but_visual_style_is_normalized():
    output = DirectingPlanOutput(visual_style="  雨夜写实，固定构图  ")
    assert output.visual_style == "雨夜写实，固定构图"
    assert output.shot_strategy.total_shots == 6
    assert output.shot_strategy.avg_duration_seconds == 5.0
    assert DirectingPlanInput().instruction == ""
    with pytest.raises(ValidationError):
        DirectingPlanInput(instruction="字" * 8001)


def test_full_saved_text_and_creative_instruction_reach_the_prompt(agent):
    text = "  第一场：旧书店\n" + "保留这一场的动作与对白。" * 4000 + "正文末尾独有线索。\n"
    inputs = DirectingPlanInput(
        script={"title": "手写稿", "script_text": text},
        shots_target=9,
        instruction="镜头保持克制，结尾多留一拍。",
    )
    variables = agent.build_variables(inputs, AgentContext(project_id="director-contract"))
    system, user, _ = agent.config_store.render_prompts(agent.config, variables)
    assert variables["script"]["script_text"] == text
    assert variables["instruction"] == inputs.instruction
    assert "正文末尾独有线索。" in user
    assert json.dumps(text, ensure_ascii=False)[1:-1] in user
    assert inputs.instruction in user
    assert "目标镜头数：9" in user
    assert "不得虚构档案 ID 或声称输入已经审核" in system


def test_postprocess_does_not_claim_that_input_profiles_are_approved(agent):
    inputs = DirectingPlanInput(scenes=[{"name": "旧书店"}])
    output = DirectingPlanOutput(visual_style="暖光下的克制写实")
    processed = agent.postprocess(output, inputs, AgentContext(project_id="director-contract"))
    assert processed.scenes_order == ["旧书店"]
    assert all("已批准" not in rule for rule in processed.continuity_rules)


def test_exported_director_schema_matches_the_runtime_model():
    root = Path(__file__).resolve().parents[2]
    exported = json.loads((root / "config/schemas/directing_plan.schema.json").read_text())
    assert exported == DirectingPlanOutput.model_json_schema()
