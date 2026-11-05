"""兼容旧运行时入口；配置缓存和进程资源仅由 platform 保存一份。"""

import sys
from importlib import import_module

_implementation = import_module("app.modules.platform.execution.runtime")
sys.modules[__name__] = _implementation
