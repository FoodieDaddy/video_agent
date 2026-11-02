"""Novel ingestion, chapter parsing and script editing."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Query, UploadFile, status
from sqlalchemy import select

from app.api.deps import RuntimeDep, SessionDep, UserDep, owner_project, project_scope, run_task
from app.api.schemas import ScriptUpdate
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.story import Script, SourceDocument, StoryEvent
from app.services import documents as document_service
from app.services import pipeline

MAX_UPLOAD_BYTES = 20 * 1024 * 1024

router = APIRouter(tags=["story"])


@router.get("/projects/{project_id}/documents")
def list_documents(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = document_service.list_documents(db, project.id)
    return {
        "items": [document_service.document_public(row) for row in rows],
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
        document = document_service.ingest_sample(db, runtime, project=project, user_id=user.id)
    else:
        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValidationAppError("文件超过 20MB 上限")
        document, _ = document_service.ingest_bytes(
            db,
            runtime,
            project=project,
            filename=file.filename or "novel.txt",
            content=content,
            content_type=file.content_type or "",
            user_id=user.id,
        )
    chapters = document_service.chapters(db, document.project_id)
    return {
        "document": document_service.document_public(document),
        "chapters": [document_service.chapter_public(row) for row in chapters],
    }


@router.get("/projects/{project_id}/chapters")
def list_chapters(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = document_service.chapters(db, project.id)
    return {"items": [document_service.chapter_public(row) for row in rows], "count": len(rows)}


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
    document = db.get(SourceDocument, document_id)
    if document is None or document.project_id != project.id:
        raise NotFoundError("文档不存在", details={"document_id": document_id})
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
    return await run_task(
        db, runtime, project=project, type="script", user_id=user.id, wait=wait
    )


@router.get("/projects/{project_id}/script")
def latest_script(db: SessionDep, project_id: str, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    script = pipeline.latest_script(db, project.id)
    if script is None:
        raise NotFoundError("该项目还没有剧本", details={"project_id": project.id})
    return _script_public(db, script)


@router.get("/projects/{project_id}/scripts")
def list_scripts(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = list(
        db.scalars(
            select(Script)
            .where(Script.project_id == project.id)
            .order_by(Script.version.desc())
        )
    )
    return {
        "items": [
            {
                "id": row.id,
                "version": row.version,
                "status": row.status,
                "title": row.title,
                "logline": row.logline,
                "approved": row.approved,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
        "count": len(rows),
    }


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
    data = payload.model_dump(exclude_unset=True)
    status_value = data.pop("status", None) or "edited"
    pipeline.update_script(db, script=script, status=status_value, **data)
    db.flush()
    return _script_public(db, script)


def _load_script(db, script_id: str) -> Script:
    script = db.get(Script, script_id)
    if script is None:
        raise NotFoundError("剧本不存在", details={"script_id": script_id})
    return script


def _script_public(db, script: Script) -> dict[str, Any]:
    payload = pipeline.script_payload(script)
    events = list(
        db.scalars(
            select(StoryEvent)
            .where(StoryEvent.script_id == script.id)
            .order_by(StoryEvent.order_index)
        )
    )
    payload.update(
        {
            "project_id": script.project_id,
            "status": script.status,
            "agent_id": script.agent_id,
            "model_id": script.model_id,
            "prompt_version": script.prompt_version,
            "config_version": script.config_version,
            "created_at": script.created_at.isoformat() if script.created_at else None,
            "events": [
                {
                    "id": event.id,
                    "order_index": event.order_index,
                    "title": event.title,
                    "description": event.description,
                    "chapter_index": event.chapter_index,
                    "location_name": event.location_name,
                    "character_names": event.character_names or [],
                    "importance": event.importance,
                }
                for event in events
            ],
        }
    )
    return payload
