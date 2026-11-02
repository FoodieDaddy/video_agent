"""Configuration contracts: no hard-coded models, one YAML per agent."""

from __future__ import annotations

REQUIRED_AGENTS = {
    "script",
    "character_extraction",
    "character_description",
    "scene_extraction",
    "scene_description",
    "director",
    "storyboard",
    "video",
    "audio",
    "editing",
    "evaluation",
}


def test_agent_configs_resolve_provider_and_prompts(runtime):
    from app.agents.registry import describe_agents

    store = runtime.config_store
    agent_ids = set(store.agent_ids())

    assert REQUIRED_AGENTS <= agent_ids
    assert len(agent_ids) >= 13

    for entry in describe_agents(store):
        # Registry and YAML must stay in sync in both directions.
        assert entry["configured"], entry["id"]
        assert entry["enabled"], entry["id"]
        assert entry["config_version"], entry["id"]
        # Every agent must point at an existing provider for its capability.
        provider = store.provider(entry["capability"], entry["provider"])
        assert provider.name == entry["provider"]

        config = store.agent(entry["id"])
        # Prompts live in files, not in Python.
        assert store.prompt_text(config.prompt.system)
        assert store.prompt_text(config.prompt.user_template)


def test_config_versions_are_stable_and_complete(runtime):
    store = runtime.config_store
    before = store.config_versions()

    assert set(before) == {f"agent:{agent_id}" for agent_id in store.agent_ids()}
    assert all(value for value in before.values())

    store.reload()
    assert store.config_versions() == before


def test_default_workflow_has_handlers_and_review_gates(runtime):
    store = runtime.config_store
    workflow = store.workflow(store.default_workflow_id())

    assert workflow.nodes
    gates = [node for node in workflow.nodes if node.type == "gate"]
    assert len(gates) >= 3
    assert all(node.review_stage for node in gates)

    handlers = [node.handler for node in workflow.nodes if node.type != "gate"]
    assert "script" in handlers
    assert "storyboard" in handlers
    assert "video" in handlers
    assert "editing" in handlers


def test_provider_yaml_never_contains_secrets(settings):
    """A provider file may *name* the variable holding the key, never the key itself."""
    import yaml

    providers_dir = settings.config_dir / "providers"
    files = sorted(providers_dir.glob("*.yaml"))
    assert files

    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "sk-" not in text, path
        entries = (yaml.safe_load(text) or {}).get("providers") or {}
        for name, provider in entries.items():
            value = str((provider or {}).get("api_key") or "")
            assert not value or value.startswith("env:"), (
                f"{path.name}:{name} must reference env:NAME instead of a literal key"
            )


def test_provider_plain_keys_resolve(monkeypatch):
    """`url` / `api_key` are the plain names; `env:NAME` reads a variable."""
    from app.core.config_models import ProviderConfig

    monkeypatch.setenv("DEMO_BASE_URL", "https://demo.example.com/v1")
    monkeypatch.setenv("DEMO_API_KEY", "secret-value")

    config = ProviderConfig(
        name="demo",
        capability="llm",
        protocol="openai_chat",
        url="env:DEMO_BASE_URL",
        api_key="env:DEMO_API_KEY",
    )
    assert config.protocol_name() == "openai_chat"
    assert config.resolved_url() == "https://demo.example.com/v1"
    assert config.resolved_api_key() == "secret-value"
    assert config.api_key_source() == "DEMO_API_KEY"

    literal = ProviderConfig(
        name="demo2",
        capability="llm",
        protocol="openai_chat",
        url="http://127.0.0.1:9880/v1",
        api_key="sk-pasted-directly",
    )
    assert literal.resolved_url() == "http://127.0.0.1:9880/v1"
    assert literal.resolved_api_key() == "sk-pasted-directly"
    # The source is never the secret itself, so it is safe to return over the API.
    assert "sk-pasted-directly" not in literal.api_key_source()


def test_provider_legacy_keys_still_work(monkeypatch):
    """Old provider files (kind/api_key_env/base_url) keep loading unchanged."""
    from app.core.config_models import ProviderConfig

    monkeypatch.setenv("LEGACY_API_KEY", "legacy-secret")
    config = ProviderConfig(
        name="legacy",
        capability="llm",
        kind="openai_chat",
        api_key_env="LEGACY_API_KEY",
        base_url="https://legacy.example.com/v1",
    )
    assert config.protocol_name() == "openai_chat"
    assert config.resolved_url() == "https://legacy.example.com/v1"
    assert config.resolved_api_key() == "legacy-secret"
