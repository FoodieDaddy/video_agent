"""旧模块路径兼容入口；唯一实现位于 studio_api.api.routes.production。"""

import sys
from importlib import import_module

_implementation = import_module("studio_api.api.routes.production")
sys.modules[__name__] = _implementation
