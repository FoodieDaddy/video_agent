"""Novel ingestion, chapter parsing and script editing."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from studio_api.api.deps import RuntimeDep, SessionDep, UserDep, owner_project, project_scope, run_task
from studio_api.api.schemas import (
    ScriptAssistRequest,
    ScriptRestoreRequest,
    ScriptUpdate,
    ScriptVersionCreate,
)
from studio_platform.exceptions import NotFoundError, ValidationAppError
from studio_story import public as story_module
from studio_story.contracts import StoryRecordReference

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_SCRIPT_IMPORT_BYTES = 2 * 1024 * 1024

router = APIRouter(tags=["story"])


@router.get("/projects/{project_id}/documents")
def list_documents(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = story_module.list_documents(db, project.id)
    return {
        "items": [story_module.document_public(row) for row in rows],
        "count": len(rows),
    }


@router.post("/projects/{project_id}/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    project_id: str,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    file: UploadFile | None = File(default=None),
    sample: bool = Query(default=False, description="导入内置示例小说"),
) -> dict[str, Any]:
    """Store the novel and split it into chapters in one step.

    Parsing is deterministic and cheap, so it runs inline; the document stays
    re-parseable later through ``/documents/{id}/parse``.
    """
    project = owner_project(db, project_id, user)
    if sample or file is None:
        document = story_module.ingest_sample(db, runtime, project=project, user_id=user.id)
    else:
        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValidationAppError("文件超过 20MB 上限")
        document, _ = story_module.ingest_bytes(
            db,
            runtime,
            project=project,
            filename=file.filename or "novel.txt",
            content=content,
            content_type=file.content_type or "",
            user_id=user.id,
        )
    chapters = story_module.chapters(db, document.project_id)
    return {
        "document": story_module.document_public(document),
        "chapters": [story_module.chapter_public(row) for row in chapters],
    }


@router.get("/projects/{project_id}/chapters")
def list_chapters(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = story_module.chapters(db, project.id)
    return {"items": [story_module.chapter_public(row) for row in rows], "count": len(rows)}


@router.post("/projects/{project_id}/documents/{document_id}/parse")
async def parse_document(
    project_id: str,
    document_id: str,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    project = owner_project(db, project_id, user)
    document = story_module.document_reference(db, project.id, document_id)
    return await run_task(
        db,
        runtime,
        project=project,
        type="parse_document",
        payload={"document_id": document.id},
        user_id=user.id,
        wait=wait,
    )


@router.post("/projects/{project_id}/analyze")
async def analyze_project(
    project_id: str,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    """Turn the parsed chapters into a structured script (one agent stage)."""
    project = owner_project(db, project_id, user)
    return await run_task(db, runtime, project=project, type="script", user_id=user.id, wait=wait)


@router.get("/projects/{project_id}/script")
def latest_script(db: SessionDep, project_id: str, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    script = story_module.latest_script_detail(db, project.id)
    if script is None:
        raise NotFoundError("该项目还没有剧本", details={"project_id": project.id})
    return script


@router.get("/projects/{project_id}/scripts")
def list_scripts(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = story_module.script_version_summaries(db, project.id)
    return {"items": rows, "count": len(rows)}


@router.post("/projects/{project_id}/scripts", status_code=status.HTTP_201_CREATED)
def create_script_version(
    project_id: str, payload: ScriptVersionCreate, db: SessionDep, user: UserDep
) -> dict[str, Any]:
    """手动新建或另存全文版本；基线冲突返回409，调用方会话统一提交。"""
    project = owner_project(db, project_id, user)
    return story_module.create_script_result(db, project=project, user_id=user.id, **payload.model_dump())


@router.post("/projects/{project_id}/scripts/import", status_code=status.HTTP_201_CREATED)
async def import_script_version(
    project_id: str,
    db: SessionDep,
    user: UserDep,
    file: UploadFile = File(...),
    base_script_id: str | None = Form(default=None),
) -> dict[str, Any]:
    """直接导入剧本而非小说；有界读取TXT/MD/JSON/DOCX，不触发模型。"""
    project = owner_project(db, project_id, user)
    # 多读一个字节即可识别超限，不把任意上传整体装入内存。
    content = await file.read(MAX_SCRIPT_IMPORT_BYTES + 1)
    if len(content) > MAX_SCRIPT_IMPORT_BYTES:
        raise ValidationAppError("剧本文件超过2MiB上限")
    return story_module.import_script_result(
        db,
        project=project,
        filename=file.filename or "script.txt",
        content=content,
        base_script_id=base_script_id or None,
        user_id=user.id,
    )


@router.post("/projects/{project_id}/scripts/{script_id}/restore", status_code=status.HTTP_201_CREATED)
def restore_script_version(
    project_id: str,
    script_id: str,
    payload: ScriptRestoreRequest,
    db: SessionDep,
    user: UserDep,
) -> dict[str, Any]:
    """复制同项目历史版本为新稿；当前版本已变化时拒绝覆盖。"""
    project = owner_project(db, project_id, user)
    return story_module.restore_script_result(
        db,
        project=project,
        script_id=script_id,
        base_script_id=payload.base_script_id,
        user_id=user.id,
    )


@router.post("/projects/{project_id}/scripts/assist", status_code=status.HTTP_202_ACCEPTED)
async def assist_script(
    project_id: str,
    payload: ScriptAssistRequest,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    """先校验已保存基线，再排队执行润色/续写；HTTP202不等于任务成功。"""
    project = owner_project(db, project_id, user)
    story_module.validate_script_assist(db, project_id=project.id, base_script_id=payload.base_script_id)
    return await run_task(
        db,
        runtime,
        project=project,
        type="script_assist",
        payload=payload.model_dump(),
        user_id=user.id,
        wait=wait,
    )


@router.get("/scripts/{script_id}")
def get_script(script_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    script = _load_script(db, script_id)
    project_scope(db, script.project_id, user)
    return _script_public(db, script)


@router.patch("/scripts/{script_id}")
def update_script(
    script_id: str,
    payload: ScriptUpdate,
    db: SessionDep,
    user: UserDep,
) -> dict[str, Any]:
    script = _load_script(db, script_id)
    # authorization only: editing a script requires owner/editor on the project
    owner_project(db, script.project_id, user)
    return story_module.patch_script_result(db, script_id=script.id, **payload.model_dump(exclude_unset=True))


def _load_script(db, script_id: str) -> StoryRecordReference:
    return story_module.script_reference(db, script_id)


def _script_public(db, script: StoryRecordReference) -> dict[str, Any]:
    return story_module.script_detail(db, script.id)
