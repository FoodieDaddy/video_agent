"""旧模块路径兼容入口；唯一实现位于 studio_api.desktop。"""

import sys
from importlib import import_module

_implementation = import_module("studio_api.desktop")
if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
