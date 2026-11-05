"""旧 story ORM 导入入口；唯一映射位于 story 模块。"""

import sys
from importlib import import_module

_implementation = import_module("studio_story.infrastructure.persistence.models")
sys.modules[__name__] = _implementation
