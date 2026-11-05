"""审核用例依赖的装配点，业务包不反向导入应用组合根。"""

from collections.abc import Callable

from app.modules.platform.exceptions import ConfigurationError
from app.modules.reviews.contracts import WorkflowReviewReader

_workflow_review_reader: WorkflowReviewReader | None = None
_default_loader: Callable[[], None] | None = None


def configure_workflow_review_reader(reader: WorkflowReviewReader) -> None:
    """由应用组合根注入；reader 不持有 Session 或可变业务数据。"""
    global _workflow_review_reader
    _workflow_review_reader = reader


def configure_default_review_loader(loader: Callable[[], None]) -> None:
    """由应用注入可选的惰性装配回调，业务模块不自行寻找实现。"""
    global _default_loader
    _default_loader = loader


def workflow_review_reader() -> WorkflowReviewReader:
    """读取已装配端口；存在应用 loader 时才惰性触发，缺失时明确报错。"""
    if _workflow_review_reader is None and _default_loader is not None:
        _default_loader()
    if _workflow_review_reader is None:
        raise ConfigurationError("审核工作流读取端口尚未装配，请通过应用组合根配置")
    return _workflow_review_reader
