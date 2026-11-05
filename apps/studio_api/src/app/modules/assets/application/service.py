"""旧模块路径兼容入口；唯一实现位于 studio_assets.application.service。"""

import sys
from importlib import import_module

_implementation = import_module("studio_assets.application.service")
sys.modules[__name__] = _implementation
