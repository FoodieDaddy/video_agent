"""旧导入路径兼容入口；实现已迁入业务模块。"""

import sys
from importlib import import_module

_module = import_module("app.modules.ai_runtime.application.execution")
import_module("app.bootstrap.agent_catalog").register_agents()
sys.modules[__name__] = _module
