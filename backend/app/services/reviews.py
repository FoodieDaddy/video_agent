"""兼容旧服务导入路径；实际实现已归入业务模块。

保留同一模块对象，使旧调用方、私有辅助函数与 monkeypatch 观察点继续有效。
"""

import sys
from importlib import import_module

from app.bootstrap.review_dependencies import configure_review_dependencies

configure_review_dependencies()
_implementation = import_module("app.modules.reviews.application.service")
sys.modules[__name__] = _implementation
