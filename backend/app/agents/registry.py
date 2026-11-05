"""旧 Agent 注册入口；兼容原 AGENT_CLASSES 的导入时可见性。"""

import sys
from importlib import import_module

_module = import_module("app.modules.ai_runtime.registry")
import_module("app.bootstrap.agent_catalog").register_agents()
sys.modules[__name__] = _module
