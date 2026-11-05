"""兼容旧服务导入路径；实际实现已归入业务模块。

保留同一模块对象，使旧调用方、私有辅助函数与 monkeypatch 观察点继续有效。
"""

import sys
from importlib import import_module

_implementation = import_module("app.modules.story.application.documents")
sys.modules[__name__] = _implementation
