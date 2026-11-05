"""应用与离线检查共用的显式装配入口。"""

from app.bootstrap.agent_catalog import register_agents
from app.bootstrap.model_catalog import register_models
from app.bootstrap.review_dependencies import configure_review_dependencies
from app.bootstrap.schema_catalog import register_schemas


def configure_application() -> None:
    """装配同一组类型与端口；不创建 engine、Runtime、线程或网络连接。"""
    register_models()
    register_schemas()
    register_agents()
    configure_review_dependencies()
