"""以文档标识调用解析能力，持久化实体不穿过工作流边界。"""

from sqlalchemy.orm import Session

from studio_platform.exceptions import NotFoundError
from studio_platform.execution.runtime import AppRuntime
from studio_story.infrastructure.persistence.models import SourceDocument

from .documents import parse_document


def parse_project_document(db: Session, runtime: AppRuntime, *, project_id: str, document_id: str) -> dict:
    """核对文档归属并解析，返回标识与章节数；仅 flush，不提交。"""
    document = db.get(SourceDocument, document_id)
    if document is None or document.project_id != project_id:
        raise NotFoundError("文档不存在", details={"document_id": document_id})
    chapters = parse_document(db, runtime, document)
    return {"document_id": document.id, "chapters": len(chapters)}
