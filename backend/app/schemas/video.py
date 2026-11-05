"""旧 Schema 导入入口；唯一类定义位于 production 模块。"""

import sys
from importlib import import_module

_implementation = import_module("app.modules.production.schemas.video")
sys.modules[__name__] = _implementation
