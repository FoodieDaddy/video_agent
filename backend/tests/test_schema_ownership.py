"""Schema 归属迁移的旧导入身份和组合装配契约。"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

OWNERS = {
    "script": "story",
    "character": "characters",
    "scene": "scenes",
    "orchestrator": "workflow",
    **{
        name: "production"
        for name in ("audio", "director", "editing", "evaluation", "prompt", "storyboard", "video")
    },
}


@pytest.mark.parametrize("name,owner", OWNERS.items())
def test_legacy_schema_import_uses_the_same_canonical_module(name, owner):
    old = importlib.import_module(f"app.schemas.{name}")
    canonical = importlib.import_module(f"studio_{owner}.schemas.{name}")
    assert old is canonical


def test_schema_catalog_keeps_existing_exports_and_shared_registry(tmp_path):
    from studio_ai_runtime import schema_registry
    from studio_api.bootstrap.schema_catalog import register_schemas

    register_schemas()
    old = importlib.import_module("app.schemas.registry")
    assert old is schema_registry
    register_schemas()
    written = schema_registry.export_schemas(tmp_path)
    config = Path(__file__).resolve().parents[2] / "config" / "schemas"
    assert len(schema_registry.OUTPUT_SCHEMAS) == 14
    assert len(written) == 7
    for path in written:
        assert json.loads(path.read_text()) == json.loads((config / path.name).read_text())
    with pytest.raises(KeyError, match="Unknown output schema"):
        schema_registry.schema_for("missing")


def test_generic_registry_import_does_not_load_business_schema_modules():
    code = """
import sys
import studio_ai_runtime.schema_registry as registry
assert registry.OUTPUT_SCHEMAS == {}
assert registry.SCHEMA_FILES == {}
assert not any(name.startswith('studio_story') for name in sys.modules)
assert not any(name.startswith('studio_production') for name in sys.modules)
assert not any(name.startswith('studio_api') for name in sys.modules)
"""
    subprocess.run([sys.executable, "-c", code], check=True)
