"""默认文字供应商契约；地址、模型、凭据均从临时 .env 验证，不读真实密钥。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DEFAULT_PROVIDER = "fast_gateway"
MODEL_REF = "env:FAST_GATEWAY_MODEL"
URL_REF = "env:FAST_GATEWAY_BASE_URL"
TEXT_AGENTS = {
    "audio",  # 文字配音规划；真实语音合成由 audio_voice 负责。
    "character_description",
    "character_extraction",
    "director",
    "editing",
    "evaluation",
    "orchestrator",
    "prompt",
    "scene_description",
    "scene_extraction",
    "script",
    "storyboard",
}


def agent_models() -> dict[str, dict]:
    """直接检查仓库声明，避免 pytest 的 mock fixture 改写默认供应商。"""
    return {
        path.stem: yaml.safe_load(path.read_text(encoding="utf-8"))["model"]
        for path in sorted((CONFIG_DIR / "agents").glob("*.yaml"))
    }


def test_text_agents_use_the_default_gateway_without_hidden_fallback():
    models = agent_models()
    text_models = {
        agent_id: model for agent_id, model in models.items() if model.get("capability") == "text_reasoning"
    }

    assert set(text_models) == TEXT_AGENTS
    for agent_id, model in text_models.items():
        assert model["provider"] == DEFAULT_PROVIDER, agent_id
        assert model["model_id"] == MODEL_REF, agent_id
        # 用户选定的默认供应商失败时，应暴露失败，避免悄悄切回本机模型。
        assert not model.get("fallback_provider"), agent_id
        assert not model.get("fallback_model_id"), agent_id


def test_gateway_declares_environment_references_for_url_model_and_key():
    providers = yaml.safe_load((CONFIG_DIR / "providers" / "llm.yaml").read_text(encoding="utf-8"))[
        "providers"
    ]
    gateway = providers[DEFAULT_PROVIDER]

    assert gateway["enabled"] is True
    assert gateway["protocol"] == "openai_chat"
    assert gateway["url"] == URL_REF
    assert gateway["api_key"] == "env:FAST_GATEWAY_API_KEY"
    assert gateway["models"] == [MODEL_REF]
    # 保留本机 Qwen 配置供显式切换，但不把它作为当前默认启用项。
    assert providers["qwen"]["enabled"] is False
    assert providers["qwen"]["protocol"] == "openai_chat"
    assert providers["qwen"]["models"]


def test_non_text_agents_keep_their_capability_specific_models():
    models = agent_models()
    expected = {
        "audio_voice": ("speech_synthesis", "mock", "mock-tts"),
        "character_consistency": ("vision", "mock", "mock-vision"),
        "character_image": ("image_generation", "mock", "mock-image"),
        "character_vision": ("vision", "mock", "mock-vision"),
        "video": ("video_generation", "minimax", "minimax-h3"),
    }
    non_text_models = {
        agent_id: model for agent_id, model in models.items() if model.get("capability") != "text_reasoning"
    }

    assert set(non_text_models) == set(expected)
    for agent_id, (capability, provider, model_id) in expected.items():
        model = non_text_models[agent_id]
        assert (model["capability"], model["provider"], model["model_id"]) == (
            capability,
            provider,
            model_id,
        ), agent_id
        assert model.get("fallback_provider") != DEFAULT_PROVIDER, agent_id
        assert model.get("fallback_model_id") != MODEL_REF, agent_id


@pytest.mark.parametrize("use_process_values", [False, True])
def test_dotenv_loads_gateway_settings_and_preserves_process_environment(
    tmp_path, monkeypatch, use_process_values
):
    """应用启动自行加载根 .env；已有环境优先，整个检查不接触真实 .env。

    显式传当前配置目录，但把 REPO_ROOT、data、storage 与数据库地址全部
    指向 pytest 临时目录。只构建配置，不启动应用或创建网络连接。
    """
    from app.core import settings as settings_module
    from app.core.config_store import ConfigStore

    dotenv_values = {
        "FAST_GATEWAY_API_KEY": "dotenv-test-credential-only",
        "FAST_GATEWAY_BASE_URL": "https://dotenv-test.invalid/v1",
        "FAST_GATEWAY_MODEL": "dotenv-test-model",
    }
    process_values = {
        "FAST_GATEWAY_API_KEY": "process-test-credential-only",
        "FAST_GATEWAY_BASE_URL": "https://process-test.invalid/v1",
        "FAST_GATEWAY_MODEL": "process-test-model",
    }
    (tmp_path / ".env").write_text(
        "".join(f"{name}={value}\n" for name, value in dotenv_values.items()), encoding="utf-8"
    )
    monkeypatch.setattr(settings_module, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("APP_ENV_FILE", str(tmp_path / ".env"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'studio.db').as_posix()}")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "")
    monkeypatch.setenv("AGENT_MODEL_ID", "")
    # 三个变量全部由测试控制：真实 .env 不会参与；dotenv 自行新增的变量
    # 也会在 teardown 撤销，避免把本例的模型或凭据泄漏给后续测试。
    for name in dotenv_values:
        monkeypatch.setenv(name, "")
        if use_process_values:
            monkeypatch.setenv(name, process_values[name])
        else:
            monkeypatch.delenv(name, raising=False)

    settings = settings_module.load_settings(config_dir=CONFIG_DIR, data_dir=tmp_path / "data")
    store = ConfigStore(settings)
    gateway = store.provider("llm", DEFAULT_PROVIDER)

    expected = process_values if use_process_values else dotenv_values
    assert gateway.resolved_api_key() == expected["FAST_GATEWAY_API_KEY"]
    assert gateway.api_key_source() == "FAST_GATEWAY_API_KEY"
    assert gateway.resolved_url() == expected["FAST_GATEWAY_BASE_URL"]
    assert gateway.models == [expected["FAST_GATEWAY_MODEL"]]
    for agent_id in TEXT_AGENTS:
        model = store.agent(agent_id).model
        assert model.provider == DEFAULT_PROVIDER, agent_id
        assert model.model_id == expected["FAST_GATEWAY_MODEL"], agent_id
    assert settings.data_dir.is_relative_to(tmp_path)
    assert settings.storage_root.is_relative_to(tmp_path)
