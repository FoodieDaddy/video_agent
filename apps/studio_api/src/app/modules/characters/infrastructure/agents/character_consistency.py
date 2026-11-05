"""旧模块路径兼容入口；唯一实现位于 studio_characters.infrastructure.agents.character_consistency。"""

import sys
from importlib import import_module

_implementation = import_module("studio_characters.infrastructure.agents.character_consistency")
sys.modules[__name__] = _implementation
