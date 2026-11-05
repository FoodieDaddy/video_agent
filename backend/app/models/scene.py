"""旧 scene ORM 导入入口；唯一映射位于 scenes 模块。"""

import sys
from importlib import import_module

_implementation = import_module("app.modules.scenes.infrastructure.persistence.models")
sys.modules[__name__] = _implementation
