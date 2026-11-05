"""旧模块路径兼容入口；唯一实现位于 studio_workflow.application.handlers。"""

import sys
from importlib import import_module

_implementation = import_module("studio_workflow.application.handlers")
sys.modules[__name__] = _implementation
