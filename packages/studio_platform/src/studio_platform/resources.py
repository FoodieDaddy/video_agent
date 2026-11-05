"""平台只消费资源根配置；业务资源由应用统一定位和交付。"""

import os
from pathlib import Path


def configured_resource_root() -> Path:
    explicit = os.environ.get("STUDIO_RESOURCE_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve()
    # 源码开发兼容；独立 platform 包安装时不要求存在应用资源。
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "config/app.yaml").is_file():
            return candidate
    return Path.cwd().resolve()


PROJECT_ROOT = configured_resource_root()
