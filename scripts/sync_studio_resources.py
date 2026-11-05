"""从正式资源目录生成 studio-api wheel 资源副本。"""

from __future__ import annotations

import shutil
from pathlib import Path


def sync_resources(root: Path) -> Path:
    """只复制 config/web/samples，绝不包含根 .env、数据库或生成媒体。"""
    target = root / "apps/studio_api/src/studio_api/resources"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("config", "web", "samples"):
        source = root / name
        if not source.is_dir():
            raise FileNotFoundError(f"资源目录不存在：{source}")
        destination = target / name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(
            source,
            destination,
            ignore=shutil.ignore_patterns("__pycache__", "node_modules", "tests", ".env", ".env.*"),
        )
    return target


if __name__ == "__main__":
    print(sync_resources(Path(__file__).resolve().parents[1]))
