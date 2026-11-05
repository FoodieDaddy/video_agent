"""跨模块契约公开入口；不集中具体业务规则。"""

from app.modules.contracts.serialization import dumps, json_safe, serialize_output

__all__ = ["dumps", "json_safe", "serialize_output"]
