"""Application settings.

Configuration is layered, from lowest to highest precedence:

1. ``config/app.yaml``
2. ``config/environments/<env>.yaml``
3. environment variables (``APP_*``, ``DATABASE_URL``, ``FFMPEG_BIN`` ...)

Secrets are never stored in YAML: only the *name* of the environment variable
holding a credential lives in the provider configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.modules.platform.resources import PROJECT_ROOT

# 配置根允许被隔离检查覆盖；独立 PROJECT_ROOT 仍为源码资源根。
REPO_ROOT = PROJECT_ROOT


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Explicit process environment values (including an intentional empty
        # value used to disable inherited overrides) always win over .env.
        os.environ.setdefault(key, value)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Config file {path} must contain a mapping at the top level")
    return payload


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into ``base`` without mutating inputs."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def resolve_binary(value: str, name: str) -> str:
    """Resolve an external binary without hard-coding a machine path.

    Order: configured value → PATH → the usual Windows/Linux install folders.
    Keeps ``config/app.yaml`` portable while letting developers install FFmpeg
    wherever they like.
    """
    import shutil

    if value and (Path(value).is_file() or shutil.which(value)):
        return value
    candidates = [
        Path(f"C:/ffmpeg/bin/{name}.exe"),
        Path(f"D:/ffmpeg/bin/{name}.exe"),
        Path.home() / "ffmpeg" / "bin" / name,
        Path("/usr/local/bin") / name,
        Path("/opt/homebrew/bin") / name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return value or name


@dataclass(frozen=True)
class Settings:
    app_name: str
    env: str
    config_dir: Path
    data_dir: Path
    storage_root: Path
    database_url: str
    inline_tasks: bool
    max_workers: int
    allow_dev_auth: bool
    demo_user_id: str
    ffmpeg_bin: str
    ffprobe_bin: str
    storage_backend: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def prompts_dir(self) -> Path:
        return self.config_dir / "prompts"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.uploads_dir, self.media_dir, self.storage_root):
            path.mkdir(parents=True, exist_ok=True)

    def get(self, *keys: str, default: Any = None) -> Any:
        """Read a nested value from the merged configuration."""
        node: Any = self.raw
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def load_settings(config_dir: Path | str | None = None, data_dir: Path | str | None = None) -> Settings:
    env = os.getenv("APP_ENV", "development")
    resolved_config_dir = Path(config_dir or os.getenv("APP_CONFIG_DIR") or REPO_ROOT / "config").resolve()
    resolved_data_dir = Path(data_dir or os.getenv("APP_DATA_DIR") or REPO_ROOT / "data").resolve()

    # Prefer an explicit env file, then the project root adjacent to config/.
    # Fall back to the source root for installations with externally mounted config.
    dotenv_path = Path(os.getenv("APP_ENV_FILE") or resolved_config_dir.parent / ".env")
    if not dotenv_path.is_file():
        dotenv_path = REPO_ROOT / ".env"
    _load_dotenv(dotenv_path)

    raw = _read_yaml(resolved_config_dir / "app.yaml")
    raw = deep_merge(raw, _read_yaml(resolved_config_dir / "environments" / f"{env}.yaml"))

    sqlite_path = (resolved_data_dir / "studio.db").as_posix()
    database_url = (
        os.getenv("DATABASE_URL") or raw.get("database", {}).get("url") or f"sqlite:///{sqlite_path}"
    )
    storage_root = Path(
        os.getenv("STORAGE_ROOT") or raw.get("storage", {}).get("root") or (resolved_data_dir / "storage")
    )
    if not storage_root.is_absolute():
        storage_root = (REPO_ROOT / storage_root).resolve()

    settings = Settings(
        app_name=os.getenv("APP_NAME") or raw.get("app", {}).get("name", "AI Film Studio"),
        env=env,
        config_dir=resolved_config_dir,
        data_dir=resolved_data_dir,
        storage_root=storage_root,
        database_url=database_url,
        inline_tasks=_as_bool(os.getenv("APP_INLINE_TASKS"), raw.get("tasks", {}).get("inline", True)),
        max_workers=int(os.getenv("APP_MAX_WORKERS") or raw.get("tasks", {}).get("max_workers", 4)),
        allow_dev_auth=_as_bool(
            os.getenv("APP_ALLOW_DEV_AUTH"), raw.get("auth", {}).get("allow_dev_auth", True)
        ),
        demo_user_id=os.getenv("APP_DEMO_USER_ID") or raw.get("auth", {}).get("demo_user_id", "user_demo"),
        ffmpeg_bin=resolve_binary(
            os.getenv("FFMPEG_BIN") or raw.get("media", {}).get("ffmpeg", "ffmpeg"), "ffmpeg"
        ),
        ffprobe_bin=resolve_binary(
            os.getenv("FFPROBE_BIN") or raw.get("media", {}).get("ffprobe", "ffprobe"), "ffprobe"
        ),
        storage_backend=os.getenv("STORAGE_BACKEND") or raw.get("storage", {}).get("backend", "local"),
        raw=raw,
    )
    settings.ensure_dirs()
    return settings
