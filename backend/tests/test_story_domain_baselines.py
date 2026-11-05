"""Story domain baseline rules without database or ORM dependencies."""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from app.modules.story.domain.script_baseline import (
    build_script_fingerprint_input,
    fingerprint_script,
    script_text_of_content,
)


def test_fingerprint_payload_preserves_existing_workflow_digest_format():
    content = {
        "id": "script_old",
        "project_id": "project_old",
        "version": 8,
        "status": "approved",
        "approved": True,
        "approved_version": 8,
        "agent_id": "script",
        "model_id": "provider/model",
        "prompt_version": "p2",
        "config_version": "c4",
        "created_at": "2026-11-01T00:00:00Z",
        "updated_at": "2026-11-02T00:00:00Z",
        "workspace_meta": {"saved": True},
        "script_text": "林简把信放在桌上。",
        "events": [{"title": "交信", "importance": 0.5}],
    }
    business_content = {
        "script_text": "林简把信放在桌上。",
        "events": [{"title": "交信", "importance": 0.5}],
    }
    legacy_payload = {
        "title": "书店",
        "logline": "一封信改变两人的选择",
        "synopsis": "剧本概要",
        "genre": "悬疑",
        "tone": "克制",
        "script_text": "林简把信放在桌上。",
        "content": business_content,
    }
    legacy_bytes = json.dumps(
        legacy_payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    value = build_script_fingerprint_input(
        title="书店",
        logline="一封信改变两人的选择",
        synopsis="剧本概要",
        genre="悬疑",
        tone="克制",
        content=content,
    )

    assert value.canonical_payload == legacy_bytes
    assert fingerprint_script(value) == hashlib.sha256(legacy_bytes).hexdigest()


def test_fingerprint_input_is_immutable_after_content_is_changed():
    content = {"script_text": "原稿", "events": [{"title": "原事件"}]}
    value = build_script_fingerprint_input(
        title="书店", logline="", synopsis="", genre="", tone="", content=content
    )
    original_digest = fingerprint_script(value)

    content["script_text"] = "修改稿"

    assert fingerprint_script(value) == original_digest
    with pytest.raises(FrozenInstanceError):
        value.canonical_payload = b"changed"


def test_script_text_projection_accepts_only_strings():
    assert script_text_of_content({"script_text": "全文"}) == "全文"
    assert script_text_of_content({"script_text": 12}) == ""
    assert script_text_of_content(None) == ""
