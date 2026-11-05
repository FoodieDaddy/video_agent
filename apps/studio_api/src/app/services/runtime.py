"""兼容旧运行时入口；配置缓存和进程资源仅由 platform 保存一份。"""

import sys
from importlib import import_module

_implementation = import_module("studio_platform.execution.runtime")
import_module("studio_api.bootstrap.agent_catalog").register_agents()
sys.modules[__name__] = _implementation
