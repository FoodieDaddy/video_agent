"""旧模块路径兼容入口；唯一实现位于 studio_platform.public。"""

import sys
from importlib import import_module

_implementation = import_module("studio_platform.public")
sys.modules[__name__] = _implementation
