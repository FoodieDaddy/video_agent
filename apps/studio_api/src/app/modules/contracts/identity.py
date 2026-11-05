"""旧模块路径兼容入口；唯一实现位于 studio_contracts.identity。"""

import sys
from importlib import import_module

_implementation = import_module("studio_contracts.identity")
sys.modules[__name__] = _implementation
