"""旧模块路径兼容入口；唯一实现位于 studio_platform.persistence.task_records。"""

import sys
from importlib import import_module

_implementation = import_module("studio_platform.persistence.task_records")
sys.modules[__name__] = _implementation
