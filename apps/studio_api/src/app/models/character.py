"""旧 character ORM 导入入口；唯一映射位于 characters 模块。"""

import sys
from importlib import import_module

_implementation = import_module("studio_characters.infrastructure.persistence.models")
sys.modules[__name__] = _implementation
