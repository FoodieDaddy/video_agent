"""应用统一定位源码或 wheel 内随包交付的资源。"""

import os
from pathlib import Path


def locate_resource_root() -> Path:
    explicit = os.environ.get("STUDIO_RESOURCE_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve()
    for candidate in Path(__file__).resolve().parents:
        if all((candidate / name).is_dir() for name in ("config", "web", "samples")):
            return candidate
    bundled = Path(__file__).resolve().parent / "resources"
    if all((bundled / name).is_dir() for name in ("config", "web", "samples")):
        return bundled
    raise RuntimeError("未找到应用资源，请设置 STUDIO_RESOURCE_ROOT 或运行资源同步后重新构建")
