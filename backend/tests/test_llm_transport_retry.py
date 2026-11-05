"""LLM传输异常归一化：MockTransport覆盖既有Agent重试额度和安全错误消息。"""

from __future__ import annotations

import asyncio
import json
import traceback

import httpx
import pytest

from app.modules.ai_runtime.base import AgentContext
from app.modules.ai_runtime.providers.base import LLMRequest
from app.modules.ai_runtime.providers.openai_compat import OpenAICompatibleLLMProvider
from app.modules.platform.configuration.config_models import GenerationConfig
from app.modules.platform.configuration.config_store import ConfigStore
from app.modules.platform.exceptions import AgentSchemaError, ProviderError
from app.modules.production.infrastructure.agents.director import DirectorAgent
from app.schemas.director import DirectingPlanInput

FAKE_SECRET = "test-only-key-do-not-echo"


def provider_with_transport(monkeypatch, handler):
    provider = OpenAICompatibleLLMProvider(
        "safe_gateway", "test-model", {"base_url": "https://transport.invalid/v1", "api_key": FAKE_SECRET}
    )
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        provider,
        "_client",
        lambda: httpx.AsyncClient(base_url="https://transport.invalid/v1", transport=transport),
    )
    return provider


@pytest.mark.parametrize("failure", [httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectError])
def test_llm_transport_is_provider_error_without_adapter_retry_or_secret(monkeypatch, failure):
    calls = []

    def handler(request):
        calls.append(request)
        raise failure(f"upstream echoed {request.headers['authorization']}", request=request)

    provider = provider_with_transport(monkeypatch, handler)
    with pytest.raises(ProviderError) as caught:
        asyncio.run(
            provider.generate(LLMRequest(system="s", user="u", generation=GenerationConfig(max_retries=7)))
        )
    assert len(calls) == 1  # adapter只发一次，额度属于外层Agent。
    assert str(caught.value) == f"safe_gateway LLM transport failed ({failure.__name__})"
    assert FAKE_SECRET not in json.dumps(caught.value.to_payload())
    assert FAKE_SECRET not in "".join(traceback.format_exception(caught.value))


def test_http_error_status_keeps_existing_message_and_no_adapter_retry(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"error": "rate limited"})

    provider = provider_with_transport(monkeypatch, handler)
    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.generate(LLMRequest(system="s", user="u")))
    assert str(caught.value).startswith("safe_gateway chat completions failed (429):")
    assert len(calls) == 1


@pytest.mark.parametrize("retries", [0, 1])
def test_existing_agent_budget_controls_disconnect_retry(monkeypatch, settings, retries):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.RemoteProtocolError(f"connection closed {FAKE_SECRET}", request=request)
        return httpx.Response(
            200,
            json={
                "id": "second-attempt",
                "choices": [{"message": {"content": json.dumps({"visual_style": "克制写实"})}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            },
        )

    provider = provider_with_transport(monkeypatch, handler)
    agent = DirectorAgent(ConfigStore(settings))
    agent.config.generation.max_retries = retries
    monkeypatch.setattr(agent, "_provider_for", lambda candidate: provider)
    if retries == 0:
        with pytest.raises(AgentSchemaError) as caught:
            asyncio.run(agent.execute(DirectingPlanInput(), AgentContext(project_id="transport-check")))
        assert len(calls) == 1 and caught.value.details["attempts"] == 1
        assert FAKE_SECRET not in str(caught.value.to_payload())
    else:
        result = asyncio.run(agent.execute(DirectingPlanInput(), AgentContext(project_id="transport-check")))
        assert len(calls) == result.attempts == 2
        assert result.output.visual_style == "克制写实"
        assert result.tokens_in == 7 and result.tokens_out == 3
