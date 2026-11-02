"""Shared pytest fixtures.

Every test gets its own SQLite database and storage root, so tests never touch
``data/studio.db`` and can run in any order.  The application is built through
:func:`app.main.create_app` exactly like production, which also exercises the
lifespan boot sequence.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    """Isolated settings pointing at a throwaway data directory."""
    data_dir: Path = tmp_path / "data"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(data_dir / 'studio.db').as_posix()}")
    monkeypatch.setenv("STORAGE_ROOT", str(data_dir / "storage"))
    # The shipped agent YAML points at real providers (a local vLLM / video
    # service); tests must never depend on those being up.
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "mock")

    from app.core.settings import get_settings, load_settings

    # The process-wide cache must not leak between tests.
    get_settings.cache_clear()
    return load_settings(data_dir=data_dir)


@pytest.fixture()
def app(settings):
    from app.main import create_app

    return create_app(settings)


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def runtime(app, client):
    """Runtime built by the lifespan handler (client fixture boots it)."""
    return app.state.runtime


@pytest.fixture()
def headers():
    return {"X-User-Id": "tester", "X-User-Role": "admin"}


@pytest.fixture()
def project(client, headers):
    response = client.post(
        "/api/v1/projects",
        json={"name": "测试项目", "genre": "悬疑"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()
