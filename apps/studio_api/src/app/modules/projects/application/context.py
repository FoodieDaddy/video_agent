"""旧模块路径兼容入口；唯一实现位于 studio_projects.application.context。"""

import sys
from importlib import import_module

_implementation = import_module("studio_projects.application.context")
sys.modules[__name__] = _implementation
