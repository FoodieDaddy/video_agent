"""AI Film Studio 应用入口与组合根。"""

import os

from .resource_root import locate_resource_root

# 一个应用只定位一次根资源；底层包可独立安装并通过显式配置使用。
os.environ.setdefault("STUDIO_RESOURCE_ROOT", str(locate_resource_root()))
