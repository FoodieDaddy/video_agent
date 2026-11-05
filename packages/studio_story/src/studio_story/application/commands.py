"""以文档标识调用解析能力，持久化实体不穿过工作流边界。"""

from typing import Any

from sqlalchemy.orm import Session

from studio_platform.exceptions import ConflictError, NotFoundError, ValidationAppError
from studio_platform.execution.runtime import AppRuntime
from studio_projects.contracts import ProjectContext
from studio_story.infrastructure.persistence.models import SourceDocument

from .documents import parse_document
from .queries import get_project_script, latest_script, script_text_of
from .use_cases import update_script
from .views import _script_record, script_detail
from .workspace import create_script_version, import_script_version, restore_script_version


def parse_project_document(db: Session, runtime: AppRuntime, *, project_id: str, document_id: str) -> dict:
    """核对文档归属并解析，返回标识与章节数；仅 flush，不提交。"""
    document = db.get(SourceDocument, document_id)
    if document is None or document.project_id != project_id:
        raise NotFoundError("文档不存在", details={"document_id": document_id})
    chapters = parse_document(db, runtime, document)
    return {"document_id": document.id, "chapters": len(chapters)}


def validate_script_assist(db: Session, *, project_id: str, base_script_id: str) -> None:
    """任务入队前按既有顺序检查所属版本、最新基线及正文，不调用模型。"""
    base = get_project_script(db, project_id, base_script_id)
    latest = latest_script(db, project_id)
    if latest is None or latest.id != base.id:
        raise ConflictError(
            "剧本已更新，请刷新并基于最新版本执行AI操作",
            details={"base_script_id": base.id, "current_script_id": latest.id if latest else None},
        )
    if not script_text_of(base).strip():
        raise ValidationAppError("当前版本没有剧本正文，请先填写正文并保存")


def patch_script_result(
    db: Session,
    *,
    script_id: str,
    title: str | None = None,
    logline: str | None = None,
    synopsis: str | None = None,
    content: dict | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """执行旧 PATCH 原位编辑并返回投影；只 flush，授权和提交由调用方负责。"""
    script = _script_record(db, script_id)
    update_script(
        db,
        script=script,
        title=title,
        logline=logline,
        synopsis=synopsis,
        content=content,
        status=status or "edited",
    )
    db.flush()
    return script_detail(db, script.id)


def create_script_result(
    db: Session,
    *,
    project: ProjectContext,
    title: str,
    script_text: str,
    logline: str = "",
    synopsis: str = "",
    base_script_id: str | None = None,
    user_id: str = "",
) -> dict[str, Any]:
    """追加手写版本并返回详情投影；旧 ORM 返回函数继续作为兼容接口保留。"""
    row = create_script_version(
        db,
        project=project,
        title=title,
        script_text=script_text,
        logline=logline,
        synopsis=synopsis,
        base_script_id=base_script_id,
        user_id=user_id,
    )
    return script_detail(db, row.id)


def import_script_result(
    db: Session,
    *,
    project: ProjectContext,
    filename: str,
    content: bytes,
    base_script_id: str | None = None,
    user_id: str = "",
) -> dict[str, Any]:
    """导入新版本并返回投影，不增加模型或事务副作用。"""
    row = import_script_version(
        db,
        project=project,
        filename=filename,
        content=content,
        base_script_id=base_script_id,
        user_id=user_id,
    )
    return script_detail(db, row.id)


def restore_script_result(
    db: Session,
    *,
    project: ProjectContext,
    script_id: str,
    base_script_id: str,
    user_id: str = "",
) -> dict[str, Any]:
    """复制历史为新版本并返回投影，旧恢复用例的冲突与错误语义保持。"""
    row = restore_script_version(
        db,
        project=project,
        script_id=script_id,
        base_script_id=base_script_id,
        user_id=user_id,
    )
    return script_detail(db, row.id)
