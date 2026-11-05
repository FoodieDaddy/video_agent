"""模块 1 的供应商选择、.env 自动读取和凭据输出回归。

配置和凭据均为临时假数据；成功/失败响应通过 MockTransport 提供，另阻断
真实 TCP 连接，防止检查脚本意外绕过测试运输层调用模型。
"""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
FAKE_KEY = "module1-private-regression-credential-unique-927"
ALT_KEY = "module1-alternative-regression-credential-581"


@pytest.fixture()
def module1(tmp_path, monkeypatch):
    """直接使用原 settings 的 .env 读取机制，替换根路径以隔离正式配置。"""
    spec = importlib.util.spec_from_file_location(
        "module1_checks_regression",
        ROOT / "scripts/checks/module1_config_llm.py",
    )
    checker = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, checker)
    spec.loader.exec_module(checker)

    config = tmp_path / "config"
    for name in ("agents", "providers", "workflows", "prompts"):
        (config / name).mkdir(parents=True)
    (config / "app.yaml").write_text("app:\n  name: Module1 Test\n", encoding="utf-8")
    llm = {
        "providers": {
            "fast_gateway": {
                "enabled": True,
                "protocol": "openai_chat",
                "url": "https://gateway.invalid/v1",
                "api_key": "env:FAST_GATEWAY_API_KEY",
                "models": ["gpt-6.1-terra"],
                "timeout_seconds": 180,
            },
            "alternative": {
                "enabled": True,
                "protocol": "openai_chat",
                "url": "https://alternative.invalid/v1",
                "api_key": "env:MODULE1_ALT_API_KEY",
                "models": ["alternative-model"],
            },
        }
    }
    (config / "providers/llm.yaml").write_text(yaml.safe_dump(llm), encoding="utf-8")
    (config / "providers/video.yaml").write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "minimax": {
                        "enabled": True,
                        "protocol": "openai_videos",
                        "url": "https://video.invalid/v1",
                        "api_key": "env:MINIMAX_API_KEY",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    for name, provider, model, capability in (
        ("script", "fast_gateway", "gpt-6.1-terra", "text_reasoning"),
        ("director", "alternative", "alternative-model", "text_reasoning"),
        ("video", "minimax", "video-test", "video_generation"),
    ):
        payload = {
            "agent": {"id": name, "name": name},
            "model": {"provider": provider, "model_id": model, "capability": capability},
            "prompt": {"system": "prompts/system.md", "user_template": "prompts/user.md"},
        }
        (config / f"agents/{name}.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")
    for name in ("system", "user"):
        (config / f"prompts/{name}.md").write_text("module1 regression", encoding="utf-8")
    (tmp_path / ".env").write_text(f"FAST_GATEWAY_API_KEY={FAKE_KEY}\n", encoding="utf-8")

    monkeypatch.setattr("app.core.settings.REPO_ROOT", tmp_path)
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    for name, value in {
        "APP_CONFIG_DIR": str(config),
        "APP_DATA_DIR": str(tmp_path / "data"),
        "DATABASE_URL": f"sqlite:///{(tmp_path / 'unused.db').as_posix()}",
        "STORAGE_ROOT": str(tmp_path / "storage"),
        "STORAGE_BACKEND": "local",
        "APP_ENV": "test",
        "AGENT_MODEL_PROVIDER": "",
        "AGENT_MODEL_ID": "",
        "MINIMAX_API_KEY": "",
        "MODULE1_ALT_API_KEY": "",
    }.items():
        monkeypatch.setenv(name, value)
    # 先记录原环境再删除，让 .env 真正负责加载；测试后 monkeypatch 会恢复原值，
    # 不把 settings 运行中写入的假凭据遗留给同进程的其他回归。
    monkeypatch.setenv("FAST_GATEWAY_API_KEY", "")
    monkeypatch.delenv("FAST_GATEWAY_API_KEY")

    connections = []
    original = socket.socket.connect
    original_ex = socket.socket.connect_ex

    def guard_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            connections.append(address)
            raise AssertionError("module1 regression forbids network connections")
        return original(sock, address)

    def guard_connect_ex(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            connections.append(address)
            raise AssertionError("module1 regression forbids network connections")
        return original_ex(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guard_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guard_connect_ex)
    yield checker, tmp_path
    assert not connections, "检查脚本企图访问真实网络"


def install_transport(monkeypatch, handler):
    original = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)


def success_response(request):
    return httpx.Response(
        200,
        json={
            "id": "fake-module1-response",
            "choices": [{"message": {"content": json.dumps({"ok": True, "module": "m1"})}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8},
        },
    )


def test_module1_reads_selected_provider_and_dotenv_without_video_key(module1, monkeypatch, capsys):
    checker, _ = module1
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "gateway.invalid"
        assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-6.1-terra"
        assert payload["max_tokens"] == 192
        assert "reasoning_effort" not in payload
        return success_response(request)

    install_transport(monkeypatch, handler)
    result = checker.main([])
    output = capsys.readouterr()
    assert result == 0
    assert len(requests) == 1
    assert output.out.count("[PASS]") == 7
    assert "selected=llm/fast_gateway" in output.out
    assert "scope=selected text provider for script" in output.out
    assert "已设置" in output.out
    assert FAKE_KEY not in output.out + output.err
    assert f"{FAKE_KEY[:3]}***{FAKE_KEY[-2:]}" not in output.out + output.err


def test_module1_all_provider_keys_is_explicit_and_fails_for_unset_video_key(module1, monkeypatch, capsys):
    checker, _ = module1
    requests = []
    install_transport(monkeypatch, lambda request: requests.append(request) or success_response(request))
    result = checker.main(["--offline", "--all-provider-keys"])
    output = capsys.readouterr()
    assert result == 1
    assert "[FAIL] 5 api key resolution" in output.out
    assert "scope=all enabled providers" in output.out
    assert "MINIMAX_API_KEY" in output.out
    assert not requests


def test_module1_missing_selected_key_fails_before_request(module1, monkeypatch, capsys):
    checker, temporary_root = module1
    (temporary_root / ".env").write_text("FAST_GATEWAY_API_KEY=\n", encoding="utf-8")
    requests = []
    install_transport(monkeypatch, lambda request: requests.append(request) or success_response(request))
    result = checker.main([])
    output = capsys.readouterr()
    assert result == 1
    assert "[FAIL] 2 enabled providers" in output.out
    assert "[FAIL] 5 api key resolution" in output.out
    assert "FAST_GATEWAY_API_KEY" in output.out
    assert "[SKIP] 6 live chat call" in output.out
    assert not requests


def test_module1_agent_option_selects_its_configured_text_provider(module1, monkeypatch, capsys):
    checker, _ = module1
    monkeypatch.setenv("MODULE1_ALT_API_KEY", ALT_KEY)
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "alternative.invalid"
        assert request.headers["authorization"] == f"Bearer {ALT_KEY}"
        assert json.loads(request.content)["model"] == "alternative-model"
        return success_response(request)

    install_transport(monkeypatch, handler)
    assert checker.main(["--agent", "director"]) == 0
    output = capsys.readouterr()
    assert len(requests) == 1
    assert "selected=llm/alternative" in output.out
    assert ALT_KEY not in output.out + output.err


def test_module1_redacts_provider_errors_in_stdout_and_stderr(module1, monkeypatch, capsys):
    checker, _ = module1

    def handler(request):
        print(f"simulated provider diagnostic: {FAKE_KEY}", file=sys.stderr)
        return httpx.Response(400, text=f"simulated gateway rejection; credential={FAKE_KEY}")

    install_transport(monkeypatch, handler)
    assert checker.main([]) == 1
    output = capsys.readouterr()
    combined = output.out + output.err
    assert "[FAIL] 6 live chat call" in output.out
    assert FAKE_KEY not in combined
    assert f"{FAKE_KEY[:3]}***{FAKE_KEY[-2:]}" not in combined
    assert "[REDACTED]" in output.out
    assert "[REDACTED]" in output.err
    assert "port 8000" not in combined
