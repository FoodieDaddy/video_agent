"""旧模块路径兼容入口；唯一实现位于 studio_ai_runtime.providers.openai_compat。"""

import sys
from importlib import import_module

_implementation = import_module("studio_ai_runtime.providers.openai_compat")
sys.modules[__name__] = _implementation
