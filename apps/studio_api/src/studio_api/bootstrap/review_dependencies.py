"""审核与工作流的应用层装配，保持业务模块依赖单向。"""


def configure_review_dependencies() -> None:
    """正式 lifespan 与兼容惰性调用均绑定工作流的同一只读函数。"""
    from studio_reviews.application.ports import configure_workflow_review_reader
    from studio_workflow.public import workflow_review_reference

    configure_workflow_review_reader(workflow_review_reference)
