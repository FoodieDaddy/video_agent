"""Application runtime container.

Holds the process-wide singletons (settings, config store, storage, task runner)
so API routes, services and background workers share one configuration snapshot.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.modules.platform.configuration.config_store import ConfigStore
from app.modules.platform.configuration.settings import Settings, load_settings
from app.modules.platform.storage import LocalStorage, S3Storage, build_storage


@dataclass
class AppRuntime:
    settings: Settings
    config_store: ConfigStore
    storage: LocalStorage | S3Storage
    task_runner: Any = None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def config_dir(self) -> Path:
        return self.settings.config_dir

    def media_path(self, storage_key: str) -> Path:
        if not isinstance(self.storage, LocalStorage):
            raise RuntimeError("Direct file access is only supported by the local storage backend")
        return self.storage.open_path(storage_key)

    def read_media(self, storage_key: str) -> bytes:
        return self.storage.read_bytes(storage_key)


_lock = threading.RLock()
_runtime: AppRuntime | None = None


def build_runtime(settings: Settings | None = None) -> AppRuntime:
    settings = settings or load_settings()
    settings.ensure_dirs()
    config_store = ConfigStore(settings)
    storage = build_storage(settings)
    return AppRuntime(settings=settings, config_store=config_store, storage=storage)


def get_runtime() -> AppRuntime:
    global _runtime
    with _lock:
        if _runtime is None:
            _runtime = build_runtime()
        return _runtime


def set_runtime(runtime: AppRuntime) -> None:
    global _runtime
    with _lock:
        _runtime = runtime


def reset_runtime() -> None:
    global _runtime
    with _lock:
        _runtime = None
