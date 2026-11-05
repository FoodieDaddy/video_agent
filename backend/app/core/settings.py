"""Compatibility alias for the canonical platform settings module.

Keep both ``sys.modules`` and the parent package attribute pointed at the same
module object. This matters for tests/tools that monkeypatch ``REPO_ROOT`` via
legacy imports before the canonical module is imported elsewhere.
"""

import sys
from importlib import import_module

_implementation = import_module("app.modules.platform.configuration.settings")
sys.modules[__name__] = _implementation
_parent = sys.modules.get("app.core")
if _parent is not None:
    _parent.settings = _implementation
