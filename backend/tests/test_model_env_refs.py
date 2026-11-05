"""模型环境引用契约：只用假模型 ID 与临时配置，不读取真实凭据或调用供应商。"""

from __future__ import annotations

import json

import pytest
import yaml
from pydantic import ValidationError

from app.core.config_models import ModelRef, ProviderConfig
from app.core.config_store import ConfigStore, stable_checksum
from app.core.exceptions import ConfigurationError
from app.core.settings import Settings


def test_agent_resolves_primary_and_fallback_model_references(monkeypatch):
    monkeypatch.setenv("MODEL_REF_TEST_PRIMARY", "primary-test-model")
    monkeypatch.setenv("MODEL_REF_TEST_BACKUP", " backup-test-model ")

    model = ModelRef(
        provider="test_gateway",
        model_id="env:MODEL_REF_TEST_PRIMARY",
        fallback_provider="backup_gateway",
        fallback_model_id=" ENV: MODEL_REF_TEST_BACKUP ",
    )

    assert model.model_id == "primary-test-model"
    assert model.fallback_model_id == "backup-test-model"
    assert model.fallback.model_id == "backup-test-model"
    assert model.fallback.provider == "backup_gateway"
    # 已加载对象保存本次有效模型；刷新配置时才重新解析环境。
    monkeypatch.setenv("MODEL_REF_TEST_PRIMARY", "another-model")
    assert model.model_id == "primary-test-model"


def test_provider_model_catalog_resolves_references_and_preserves_url_resolution(monkeypatch):
    monkeypatch.setenv("MODEL_REF_TEST_PRIMARY", "primary-test-model")
    monkeypatch.setenv("MODEL_REF_TEST_URL", "https://model-ref-test.invalid/v1")

    provider = ProviderConfig(
        name="test_gateway",
        capability="llm",
        protocol="openai_chat",
        url="env:MODEL_REF_TEST_URL",
        models=["env:MODEL_REF_TEST_PRIMARY", "literal-model"],
    )

    assert provider.models == ["primary-test-model", "literal-model"]
    assert provider.url == "env:MODEL_REF_TEST_URL"
    assert provider.resolved_url() == "https://model-ref-test.invalid/v1"


@pytest.mark.parametrize("value", [None, "", "  \t"])
@pytest.mark.parametrize("field", ["model_id", "fallback_model_id", "models"])
def test_missing_or_empty_model_environment_is_a_clear_error(monkeypatch, value, field):
    name = "MODEL_REF_TEST_MISSING"
    if value is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match=name):
        if field == "models":
            ProviderConfig(name="test_gateway", capability="llm", models=[f"env:{name}"])
        else:
            values = {"provider": "test_gateway", "model_id": "literal-model", field: f"env:{name}"}
            ModelRef(**values)


def test_model_reference_needs_a_variable_name_and_a_concrete_value(monkeypatch):
    with pytest.raises(ValidationError, match="缺少环境变量名"):
        ModelRef(provider="test_gateway", model_id="env: ")

    monkeypatch.setenv("MODEL_REF_TEST_NESTED", "env:ANOTHER_VARIABLE")
    with pytest.raises(ValidationError, match="MODEL_REF_TEST_NESTED.*具体模型"):
        ModelRef(provider="test_gateway", model_id="env:MODEL_REF_TEST_NESTED")


def test_literal_models_and_legacy_provider_fields_keep_existing_behavior():
    model = ModelRef(provider="legacy", model_id="literal-model", fallback_model_id=None)
    provider = ProviderConfig(
        name="legacy",
        capability="llm",
        kind="openai_chat",
        base_url="https://legacy-test.invalid/v1",
        models=["literal-model", "backup-model"],
    )

    assert model.model_id == "literal-model" and model.fallback is None
    assert provider.models == ["literal-model", "backup-model"]
    assert provider.protocol_name() == "openai_chat"
    assert provider.resolved_url() == "https://legacy-test.invalid/v1"


def test_model_validator_does_not_read_dotenv_itself(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MODEL_REF_TEST_NOT_LOADED", raising=False)
    (tmp_path / ".env").write_text("MODEL_REF_TEST_NOT_LOADED=not-loaded-model\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="MODEL_REF_TEST_NOT_LOADED"):
        ModelRef(provider="test_gateway", model_id="env:MODEL_REF_TEST_NOT_LOADED")


def config_fixture(tmp_path, monkeypatch, model=None, catalog=None):
    """构造最小配置目录，避免测试依赖当前根目录 .env 或正式 YAML。"""
    config_dir = tmp_path / "config"
    for child in ("agents", "providers", "workflows", "prompts"):
        (config_dir / child).mkdir(parents=True)
    payload = {
        "agent": {"id": "script", "name": "script-test", "enabled": True},
        "model": model
        or {
            "provider": "test_gateway",
            "model_id": "env:MODEL_REF_TEST_PRIMARY",
            "fallback_provider": "test_gateway",
            "fallback_model_id": "env:MODEL_REF_TEST_BACKUP",
        },
        "generation": {"temperature": 0.3, "max_output_tokens": 512},
        "prompt": {"system": "prompts/system.md", "user_template": "prompts/user.md", "version": "1.0.0"},
        "runtime": {"concurrency": 1},
        "evaluation": {"enabled": True},
    }
    agent_path = config_dir / "agents/script.yaml"
    agent_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    provider = {
        "providers": {
            "test_gateway": {
                "enabled": True,
                "protocol": "openai_chat",
                "url": "https://model-ref-test.invalid/v1",
                "models": catalog
                if catalog is not None
                else ["env:MODEL_REF_TEST_PRIMARY", "env:MODEL_REF_TEST_BACKUP"],
            }
        }
    }
    (config_dir / "providers/llm.yaml").write_text(yaml.safe_dump(provider), encoding="utf-8")
    for name in ("system", "user"):
        (config_dir / f"prompts/{name}.md").write_text(f"unchanged {name} prompt", encoding="utf-8")
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "")
    monkeypatch.setenv("AGENT_MODEL_ID", "")
    settings = Settings(
        app_name="model-ref-test",
        env="test",
        config_dir=config_dir,
        data_dir=tmp_path / "data",
        storage_root=tmp_path / "storage",
        database_url=f"sqlite:///{(tmp_path / 'unused.db').as_posix()}",
        inline_tasks=True,
        max_workers=1,
        allow_dev_auth=True,
        demo_user_id="model-ref-test",
        ffmpeg_bin="ffmpeg",
        ffprobe_bin="ffprobe",
        storage_backend="local",
    )
    return settings, agent_path, payload


def test_config_fingerprint_changes_with_effective_primary_and_fallback_models(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_REF_TEST_PRIMARY", "primary-v1")
    monkeypatch.setenv("MODEL_REF_TEST_BACKUP", "backup-v1")
    settings, agent_path, original = config_fixture(tmp_path, monkeypatch)
    store = ConfigStore(settings)
    first = store.agent("script").config_version
    prompts = store.prompt_version("prompts/system.md", "prompts/user.md")

    monkeypatch.setenv("MODEL_REF_TEST_PRIMARY", "primary-v2")
    store.reload()
    second = store.agent("script").config_version
    assert second != first
    assert store.agent("script").model.model_id == "primary-v2"
    assert store.provider("llm", "test_gateway").models == ["primary-v2", "backup-v1"]

    monkeypatch.setenv("MODEL_REF_TEST_BACKUP", "backup-v2")
    store.reload()
    third = store.agent("script").config_version
    assert third != second
    assert store.prompt_version("prompts/system.md", "prompts/user.md") == prompts
    assert store.agent("script").generation.max_output_tokens == 512
    assert yaml.safe_load(agent_path.read_text()) == original

    # 相同有效模型改为字面量后沿用原字段集合，不能因引用写法不同而改变有效指纹。
    literal = json.loads(json.dumps(original))
    literal["model"].update(model_id="primary-v2", fallback_model_id="backup-v2")
    agent_path.write_text(yaml.safe_dump(literal), encoding="utf-8")
    store.reload()
    assert store.agent("script").config_version == third
    assert third == stable_checksum(
        {
            key: literal.get(key)
            for key in (
                "agent",
                "model",
                "generation",
                "structured_output",
                "prompt",
                "runtime",
                "evaluation",
            )
        }
    )


def test_model_references_preserve_admin_and_process_override_priority(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_REF_TEST_PRIMARY", "yaml-model")
    monkeypatch.setenv("MODEL_REF_TEST_BACKUP", "yaml-backup")
    settings, _, _ = config_fixture(tmp_path, monkeypatch)
    store = ConfigStore(settings)

    store.apply_overrides({"script": {"model": {"model_id": "admin-model"}}})
    assert store.agent("script").model.model_id == "admin-model"
    assert store.agent("script").model.fallback_model_id == "yaml-backup"

    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "forced_gateway")
    monkeypatch.setenv("AGENT_MODEL_ID", "env:MODEL_REF_TEST_FORCED")
    monkeypatch.setenv("MODEL_REF_TEST_FORCED", "process-model")
    store.reload()
    assert store.agent("script").model.provider == "forced_gateway"
    assert store.agent("script").model.model_id == "process-model"


def test_config_store_names_invalid_agent_or_provider_reference(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_REF_TEST_PRIMARY", raising=False)
    monkeypatch.setenv("MODEL_REF_TEST_BACKUP", "backup-model")
    settings, agent_path, payload = config_fixture(tmp_path, monkeypatch)
    with pytest.raises(ConfigurationError, match="MODEL_REF_TEST_PRIMARY") as agent_error:
        ConfigStore(settings)
    assert "script.yaml" in str(agent_error.value)

    payload["model"]["model_id"] = "literal-model"
    agent_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="MODEL_REF_TEST_PRIMARY") as provider_error:
        ConfigStore(settings)
    assert "test_gateway" in str(provider_error.value) and "llm.yaml" in str(provider_error.value)
