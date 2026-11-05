from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import app.modules.platform.security as security
from app.modules.platform.configuration.settings import Settings
from app.modules.platform.exceptions import PermissionDeniedError


def test_client_cannot_select_admin_role_outside_local_environments(monkeypatch):
    production = Settings(
        app_name="test", env="production", config_dir=Path("."), data_dir=Path("."),
        storage_root=Path("."), database_url="sqlite://", inline_tasks=True,
        max_workers=1, allow_dev_auth=True, demo_user_id="demo", ffmpeg_bin="ffmpeg",
        ffprobe_bin="ffprobe", storage_backend="local", raw={},
    )
    monkeypatch.setattr(security, "_settings", lambda: production)
    with pytest.raises(PermissionDeniedError):
        asyncio.run(security.get_current_user(x_user_id="attacker", x_user_role="admin"))
