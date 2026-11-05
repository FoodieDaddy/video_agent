"""旧 Schema 注册入口；装配默认业务类型后转发到通用注册表。"""

import sys
from importlib import import_module

_module = import_module("app.modules.ai_runtime.schema_registry")
import_module("app.bootstrap.schema_catalog").register_schemas()
sys.modules[__name__] = _module
