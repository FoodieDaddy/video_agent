"""剧本编辑契约回归：模型结果全部由本地替身提供，不启动服务或访问模型。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.ai_runtime.base import AgentContext
from app.modules.ai_runtime.providers.base import LLMRequest, LLMResult
from app.modules.ai_runtime.providers.mock import MockLLMProvider
from app.modules.ai_runtime.registry import agent_ids
from app.modules.platform.configuration.config_store import ConfigStore
from app.modules.platform.exceptions import AgentSchemaError
from app.modules.story.contracts import ScriptInput, ScriptOutput, StoryEventDraft
from app.modules.story.infrastructure.agents.script import ScriptAgent

ORIGINAL = "第一场 夜 内 旧书店\n林简推开门，苏晚将一封信放在柜台上。"
ADDITION = "第二场 夜 外 街道\n林简收起信，街角传来一声短促的汽笛。"


class ScriptReplies:
    """记录真实执行链提交的请求，只回放本例预先指定的结构化候选。"""

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = replies
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResult:
        self.requests.append(request)
        reply = self.replies[min(len(self.requests) - 1, len(self.replies) - 1)]
        return LLMResult(
            text=json.dumps(reply, ensure_ascii=False),
            structured=reply,
            provider="script-test-double",
            model_id="offline-script",
            tokens_in=10,
            tokens_out=20,
        )


@pytest.fixture()
def agent(settings) -> ScriptAgent:
    """只加载现有模板与配置；不使用会启动应用的 runtime/client fixture。"""
    store = ConfigStore(settings)
    config = store.agent("script").model_copy(deep=True)
    config.generation.max_retries = 1
    config.structured_output.repair_attempts = 1
    return ScriptAgent(store, config)


def connect_replies(agent: ScriptAgent, monkeypatch, *replies: dict[str, Any]) -> ScriptReplies:
    provider = ScriptReplies(list(replies))
    monkeypatch.setattr(agent, "_provider_for", lambda model_ref: provider)
    return provider


def edited_output(text: str) -> dict[str, Any]:
    """正文含义由 operation 约定，结构仍描述操作后的完整故事。"""
    return {
        "title": "雨夜的信",
        "script_text": text,
        "chapters": [{"index": 1, "title": "雨夜", "summary": "书店交接后，林简走向街道。"}],
        "events": [{"title": "交接与离开", "description": "林简取信离开书店。", "importance": 0.8}],
    }


def test_original_analysis_input_and_output_remain_compatible():
    inputs = ScriptInput(chapters=[{"title": "原章节", "content": ORIGINAL}])
    output = ScriptOutput(title="旧版分析结果")

    assert inputs.operation == "analyze"
    assert inputs.script_text == ""
    assert inputs.current_script == {}
    assert output.script_text == ""


@pytest.mark.parametrize("operation", ["polish", "continue"])
@pytest.mark.parametrize("text", ["", " \n\t "])
def test_revisions_require_explicit_nonempty_current_text(operation, text):
    # 即使传了旧结构中的正文或章节，也不能替代显式的 script_text，避免来源歧义。
    with pytest.raises(ValidationError, match="非空的 script_text"):
        ScriptInput(
            operation=operation,
            script_text=text,
            current_script={"script_text": ORIGINAL},
            chapters=[{"content": ORIGINAL}],
        )


def test_unknown_operation_is_rejected():
    with pytest.raises(ValidationError):
        ScriptInput(operation="rewrite", script_text=ORIGINAL)


def test_full_revision_text_and_structure_reach_rendered_prompt(agent):
    text = "保留空格：  \n" + "现稿细节。" * 5000 + "末尾独有线索。\n"
    inputs = ScriptInput(
        operation="continue",
        script_text=text,
        current_script={"title": "现稿标题", "dialogues": [{"character_name": "苏晚", "text": "等我。"}]},
        instruction="延续末尾线索，不新增人物。",
    )

    variables = agent.build_variables(inputs, AgentContext(project_id="project-test"))
    system, user, _ = agent.config_store.render_prompts(agent.config, variables)

    assert variables["script_text"] == text
    assert text in user
    assert "末尾独有线索。" in user
    assert inputs.instruction in user
    assert "现稿标题" in user and "苏晚" in user
    assert "continue" in user
    assert "只能返回新增正文" in system
    assert "应用层会原样保留原稿" in system


def test_analysis_fills_old_structure_and_renders_an_editable_draft(agent):
    inputs = ScriptInput(chapters=[{"title": "第一章", "content": ORIGINAL}])
    output = agent.postprocess(ScriptOutput(title="分析"), inputs, AgentContext(project_id="project-test"))

    assert "【第1章 第一章】" in output.script_text
    assert "【事件1 第一章】" in output.script_text
    assert ORIGINAL not in output.script_text
    assert len(output.chapters) == len(output.events) == 1
    assert output.chapters[0].title == "第一章"
    assert output.events[0].chapter_index == 1


def test_polish_returns_complete_candidate_without_appending_original(agent, monkeypatch):
    polished = "第一场 夜 内 旧书店\n雨水顺着门框滑落。林简接过苏晚递来的信。"
    provider = connect_replies(agent, monkeypatch, edited_output(polished))
    inputs = agent.validate_input({"operation": "polish", "script_text": ORIGINAL, "instruction": "对白简洁"})

    result = asyncio.run(agent.execute(inputs, AgentContext(project_id="project-test")))

    assert result.output.script_text == polished
    assert inputs.script_text == ORIGINAL
    assert provider.requests[0].prompt_vars["operation"] == "polish"
    assert result.attempts == 1


def test_continue_returns_only_addition_and_leaves_application_merge_to_caller(agent, monkeypatch):
    provider = connect_replies(agent, monkeypatch, edited_output(ADDITION))
    inputs = agent.validate_input({"operation": "continue", "script_text": ORIGINAL})

    result = asyncio.run(agent.execute(inputs, AgentContext(project_id="project-test")))

    assert result.output.script_text == ADDITION
    assert ORIGINAL not in result.output.script_text
    assert inputs.script_text == ORIGINAL
    assert provider.requests[0].prompt_vars["script_text"] == ORIGINAL
    assert result.output.chapters[0].summary == "书店交接后，林简走向街道。"


@pytest.mark.parametrize(
    ("operation", "candidate"),
    [
        ("polish", ""),
        ("polish", " \n\t"),
        ("continue", ""),
        ("continue", " \n\t"),
        ("continue", ORIGINAL),
        ("continue", ORIGINAL + "\n\n" + ADDITION),
        ("continue", " \n" + ORIGINAL + "\n\n" + ADDITION),
    ],
)
def test_unusable_revision_is_repaired_then_fails_without_original_text_fallback(
    agent, monkeypatch, operation, candidate
):
    provider = connect_replies(agent, monkeypatch, edited_output(candidate))
    inputs = ScriptInput(operation=operation, script_text=ORIGINAL)

    with pytest.raises(AgentSchemaError) as error:
        asyncio.run(agent.execute(inputs, AgentContext(project_id="project-test")))

    assert error.value.details["attempts"] == 2
    assert len(provider.requests) == 2
    assert "上一次输出没有通过结构化校验" in provider.requests[1].user
    assert inputs.script_text == ORIGINAL


def test_continue_repair_can_replace_a_repeated_original_with_valid_new_text(agent, monkeypatch):
    provider = connect_replies(
        agent, monkeypatch, edited_output(ORIGINAL + ADDITION), edited_output(ADDITION)
    )
    inputs = ScriptInput(operation="continue", script_text=ORIGINAL)

    result = asyncio.run(agent.execute(inputs, AgentContext(project_id="project-test")))

    assert result.output.script_text == ADDITION
    assert result.attempts == 2
    assert result.meta["repairs"] == 1
    assert "不得回显或以完整原稿开头" in provider.requests[1].user


def test_revision_does_not_fill_missing_new_structure_from_old_chapters(agent):
    inputs = ScriptInput(
        operation="continue", script_text=ORIGINAL, chapters=[{"title": "旧章", "content": ORIGINAL}]
    )
    output = agent.postprocess(
        ScriptOutput(title="续写", script_text=ADDITION), inputs, AgentContext(project_id="project-test")
    )

    assert output.chapters == []
    assert output.events == []


def test_event_importance_clamping_remains_available_for_all_operations(agent):
    inputs = ScriptInput(operation="polish", script_text=ORIGINAL)
    output = ScriptOutput(
        title="润色",
        script_text=ORIGINAL,
        events=[StoryEventDraft(title="交接", description="取信", importance=4.0)],
    )

    assert (
        agent.postprocess(output, inputs, AgentContext(project_id="project-test")).events[0].importance == 1.0
    )


def test_new_operations_reuse_existing_script_agent_id():
    ids = agent_ids()
    assert len(ids) == 17
    assert ids.count("script") == 1


def test_analysis_draft_uses_validated_structure_and_preserves_existing_model_body(agent):
    inputs = ScriptInput(chapters=[{"title": "原章", "content": "不应直接复制的原文章节正文"}])
    output = ScriptOutput.model_validate(edited_output(""))
    rendered = agent.postprocess(output, inputs, AgentContext(project_id="project-test"))
    assert "书店交接后，林简走向街道。" in rendered.script_text
    assert "取信离开书店" in rendered.script_text
    assert "不应直接复制的原文章节正文" not in rendered.script_text

    model_body = "  模型已经返回的完整正文。\n"
    candidate = ScriptOutput.model_validate(edited_output(model_body))
    assert (
        agent.postprocess(candidate, inputs, AgentContext(project_id="project-test")).script_text
        == model_body
    )


def test_title_only_legacy_analysis_does_not_invent_a_draft(agent):
    output = agent.postprocess(
        ScriptOutput(title="只有标题"), ScriptInput(), AgentContext(project_id="project-test")
    )
    assert output.script_text == ""


@pytest.mark.parametrize("operation", ["analyze", "polish", "continue"])
def test_all_operations_work_through_explicit_mock_provider(agent, monkeypatch, operation):
    """真实 Agent 执行链接到仓库离线 Provider，而非 HTTP 或在线模型。"""
    monkeypatch.setattr(agent, "_provider_for", lambda model_ref: MockLLMProvider())
    source = ORIGINAL + "...  \n"
    inputs = ScriptInput(
        operation=operation,
        script_text=source if operation != "analyze" else "",
        chapters=[{"index": 1, "title": "书店交接", "content": ORIGINAL}] if operation == "analyze" else [],
        current_script=edited_output(source) if operation != "analyze" else {},
    )

    result = asyncio.run(agent.execute(inputs, AgentContext(project_id="project-test")))

    assert result.output.script_text.strip()
    assert result.meta["provider_meta"]["offline"] is True
    if operation == "polish":
        assert result.output.script_text == source.replace("...", "……").strip()
    elif operation == "continue":
        assert result.output.script_text.startswith("【续写示例】")
        assert source.strip() not in result.output.script_text
        assert len(result.output.chapters) == 2
        assert result.output.events[-1].title == "续写示例"
    else:
        assert "【事件1 书店交接】" in result.output.script_text
