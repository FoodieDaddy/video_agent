"""兼容原任务入口；唯一业务分派实现位于 workflow 模块。"""

import sys
from importlib import import_module

_implementation = import_module("app.modules.workflow.application.task_dispatch")
sys.modules[__name__] = _implementation
