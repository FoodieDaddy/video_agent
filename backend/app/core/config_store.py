"""兼容旧导入路径；唯一实现位于 ``app.modules.platform.configuration.config_store``。

模块别名保留类、缓存、全局资源和 monkeypatch 的对象身份，不复制实现。
"""

import sys
from importlib import import_module

_implementation = import_module("app.modules.platform.configuration.config_store")
sys.modules[__name__] = _implementation
