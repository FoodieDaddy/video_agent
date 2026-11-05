"""跨模块契约公开入口；不集中具体业务规则。"""

from studio_contracts.identity import ProjectIdentity
from studio_contracts.serialization import dumps, json_safe, serialize_output

__all__ = ["ProjectIdentity", "dumps", "json_safe", "serialize_output"]
