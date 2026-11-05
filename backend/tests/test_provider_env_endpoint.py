"""显式环境URL缺失时必须停止，不能带着其他供应商凭据回落默认地址。

所有配置和凭据均为假数据；这些测试不加载正式.env、不发请求、不启动服务。
同时记录HTTP与TCP企图，避免被测检查器吞掉异常后仍掩盖意外联网。
"""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from app.core.config_models import ModelRef, ProviderConfig
from app.core.exceptions import ProviderUnavailableError
from app.providers import registry
from app.providers.openai_compat import OpenAICompatibleLLMProvider

ROOT = Path(__file__).resolve().parents[2]
URL_VAR = "ENDPOINT_REGRESSION_BASE_URL"
KEY_VAR = "ENDPOINT_REGRESSION_API_KEY"
FAKE_KEY = "endpoint-regression-fake-credential-38729"


class EndpointStore:
    """只实现factory和模块1使用的读取接口，不依赖磁盘或正式ConfigStore。"""

    def __init__(self, url: str | None = f"env:{URL_VAR}", **updates):
        self.config = ProviderConfig(
            name="endpoint_test",
            capability="llm",
            enabled=True,
            protocol="openai_chat",
            url=url,
            api_key=f"env:{KEY_VAR}",
            models=["endpoint-fixture-model"],
            **updates,
        )
        self.model = ModelRef(provider="endpoint_test", model_id="endpoint-fixture-model")

    def provider(self, capability, name):
        assert capability == "llm" and name == self.config.name
        return self.config

    def providers(self, capability=None):
        return {self.config.name: self.config} if capability in (None, "llm") else {}

    def agent(self, agent_id):
        assert agent_id == "script"
        return SimpleNamespace(model=self.model)

    def try_agent(self, agent_id):
        return self.agent(agent_id) if agent_id == "script" else None

    def agent_ids(self):
        return ["script"]


@pytest.fixture(autouse=True)
def isolated_credentials_and_no_network(monkeypatch):
    monkeypatch.setenv(KEY_VAR, FAKE_KEY)
    monkeypatch.delenv(URL_VAR, raising=False)
    attempts = []

    async def deny_send(*args, **kwargs):
        attempts.append("http")
        raise AssertionError("endpoint regression forbids HTTP requests")

    original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def deny_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            attempts.append("tcp")
            raise AssertionError("endpoint regression forbids TCP connections")
        return original_connect(sock, address)

    def deny_connect_ex(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            attempts.append("tcp")
            raise AssertionError("endpoint regression forbids TCP connections")
        return original_connect_ex(sock, address)

    monkeypatch.setattr(httpx.AsyncClient, "send", deny_send)
    monkeypatch.setattr(socket.socket, "connect", deny_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_connect_ex)
    yield
    assert not attempts, f"出现不应发生的网络请求：{attempts}"


@pytest.mark.parametrize("missing", [None, "", "  \t"])
def test_runtime_rejects_missing_explicit_env_url_before_constructing_client(monkeypatch, missing):
    if missing is not None:
        monkeypatch.setenv(URL_VAR, missing)
    # 即使还存在旧base_url，显式env引用也不能悄悄改用那个历史目的地址。
    store = EndpointStore(base_url="https://legacy.invalid/v1")
    constructor = Mock(side_effect=AssertionError("provider construction should not happen"))
    monkeypatch.setitem(registry._PROTOCOL_IMPLS, ("llm", "openai_chat"), constructor)

    with pytest.raises(ProviderUnavailableError, match=URL_VAR) as caught:
        registry.get_llm(store, store.model)

    assert caught.value.details["url_env"] == URL_VAR
    assert FAKE_KEY not in str(caught.value) + json.dumps(caught.value.details)
    constructor.assert_not_called()


def test_runtime_resolves_complete_env_endpoint(monkeypatch):
    monkeypatch.setenv(URL_VAR, "https://selected.invalid/v1")
    store = EndpointStore()

    provider = registry.get_llm(store, store.model)

    assert isinstance(provider, OpenAICompatibleLLMProvider)
    assert provider.options["base_url"] == "https://selected.invalid/v1"
    assert provider.options["api_key"] == FAKE_KEY
    assert provider.model_id == "endpoint-fixture-model"


@pytest.mark.parametrize(
    "url, legacy_url, expected",
    [
        ("https://literal.invalid/v1", None, "https://literal.invalid/v1"),
        (None, "https://legacy.invalid/v1", "https://legacy.invalid/v1"),
        (None, None, None),
    ],
)
def test_runtime_preserves_literal_and_unstated_url_compatibility(url, legacy_url, expected):
    store = EndpointStore(url=url, base_url=legacy_url)

    provider = registry.get_llm(store, store.model)

    assert isinstance(provider, OpenAICompatibleLLMProvider)
    assert provider.options["base_url"] == expected


@pytest.fixture()
def module1(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "module1_endpoint_regression",
        ROOT / "scripts/checks/module1_config_llm.py",
    )
    checker = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, checker)
    spec.loader.exec_module(checker)
    return checker


def test_module1_readiness_fails_when_selected_env_url_is_missing(module1):
    report = module1.Report()

    module1.check_providers(EndpointStore(), report)

    assert report.rows[-1][0] == "2 enabled providers"
    assert report.rows[-1][1] == "FAIL"
    assert URL_VAR in report.rows[-1][2]


def test_module1_factory_does_not_return_an_invalid_legacy_client(module1):
    """runtime可保留无URL旧配置，但配置自检不应把这种客户端交给live组。"""
    report = module1.Report()

    provider = module1.check_factory(EndpointStore(url=None), "script", report)

    assert provider is None
    assert report.rows[-1][0] == "4 provider factory"
    assert report.rows[-1][1] == "FAIL"


@pytest.mark.parametrize("url", [f"env:{URL_VAR}", None])
def test_module1_invalid_endpoint_never_invokes_live_group(module1, monkeypatch, tmp_path, url):
    store = EndpointStore(url=url)

    def loaded_config(settings, report):
        report.add("1 settings + ConfigStore", "PASS", "isolated fixture")
        return store, []

    monkeypatch.setattr(
        module1, "load_settings", lambda: SimpleNamespace(config_dir=tmp_path, data_dir=tmp_path)
    )
    monkeypatch.setattr(module1, "check_config", loaded_config)
    live = Mock(side_effect=AssertionError("live group must not run"))
    monkeypatch.setattr(module1, "check_live", live)

    result = module1.main([])

    assert result == 1
    live.assert_not_called()
