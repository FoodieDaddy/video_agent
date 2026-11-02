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
    providers_dir = settings.config_dir / "providers"
    files = sorted(providers_dir.glob("*.yaml"))
    assert files

    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "sk-" not in text, path
        assert "api_key:" not in text, path
