"""旧 production ORM 导入入口；唯一映射位于 production 模块。"""

import sys
from importlib import import_module

_implementation = import_module("app.modules.production.infrastructure.persistence.models")
sys.modules[__name__] = _implementation
