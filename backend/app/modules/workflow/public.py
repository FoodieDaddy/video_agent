"""workflow 模块公开入口；跨模块调用仅依赖此处声明的操作。"""

from app.modules.workflow.application.engine import (
    WorkflowEngine,
    cancel,
    checkpoints,
    get_run,
    latest_run,
    list_runs,
    run_public,
)
from app.modules.workflow.application.handlers import (
    Handler,
    HandlerContext,
    build_handlers,
    handle_audio,
    handle_character_assets,
    handle_characters,
    handle_directing,
    handle_editing,
    handle_evaluation,
    handle_export,
    handle_render,
    handle_scenes,
    handle_script,
    handle_storyboard,
    handle_video,
    handler_names,
    require_handler,
)
from app.modules.workflow.application.review_queries import workflow_review_reference

__all__ = [
    "workflow_review_reference",
    "WorkflowEngine",
    "get_run",
    "latest_run",
    "list_runs",
    "checkpoints",
    "run_public",
    "cancel",
    "HandlerContext",
    "handle_script",
    "handle_characters",
    "handle_scenes",
    "handle_directing",
    "handle_storyboard",
    "handle_character_assets",
    "handle_video",
    "handle_audio",
    "handle_editing",
    "handle_render",
    "handle_evaluation",
    "handle_export",
    "build_handlers",
    "handler_names",
    "require_handler",
    "Handler",
]


__all__.append("tasks")


def __getattr__(name):
    """任务调度门面按需加载，避免工作流装配时建立反向导入。"""
    if name == "tasks":
        from importlib import import_module

        return import_module("app.modules.workflow.application.task_dispatch")
    raise AttributeError(name)
