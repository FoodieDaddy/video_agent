"""旧模块路径兼容入口；唯一实现位于 studio_api.bootstrap.schema_catalog。"""

import sys
from importlib import import_module

_implementation = import_module("studio_api.bootstrap.schema_catalog")
sys.modules[__name__] = _implementation
