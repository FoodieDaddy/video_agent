"""旧导入路径兼容入口；实现已迁入业务模块。"""

import sys
from importlib import import_module

_module = import_module("studio_production.infrastructure.agents.editing")
sys.modules[__name__] = _module
