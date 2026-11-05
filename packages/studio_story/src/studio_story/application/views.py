"""剧本和文档的公开读取投影；所有数据库读取留在 story 所有者内。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from studio_platform.exceptions import NotFoundError
from studio_story.contracts import StoryRecordReference
from studio_story.infrastructure.persistence.models import Script, SourceDocument, StoryEvent

from .queries import latest_script, list_script_versions, script_payload


def _script_record(db: Session, script_id: str) -> Script:
    """保留无项目路径接口先检查记录是否存在的旧错误语义。"""
    row = db.get(Script, script_id)
    if row is None:
        raise NotFoundError("剧本不存在", details={"script_id": script_id})
    return row


def script_reference(db: Session, script_id: str) -> StoryRecordReference:
    """读取最少身份字段供入口随后授权；记录不存在先返回旧 404。"""
    row = _script_record(db, script_id)
    return StoryRecordReference(id=row.id, project_id=row.project_id)


def document_reference(db: Session, project_id: str, document_id: str) -> StoryRecordReference:
    """按项目核对待解析源文档；不存在或归属不同保持相同错误。"""
    row = db.get(SourceDocument, document_id)
    if row is None or row.project_id != project_id:
        raise NotFoundError("文档不存在", details={"document_id": document_id})
    return StoryRecordReference(id=row.id, project_id=row.project_id)


def _script_detail_of(db: Session, script: Script) -> dict[str, Any]:
    """保持剧本响应字段与事件排序，嵌套字典不再共享 ORM JSON 值。"""
    payload = script_payload(script)
    events = db.scalars(
        select(StoryEvent).where(StoryEvent.script_id == script.id).order_by(StoryEvent.order_index)
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
    return deepcopy(payload)


def script_detail(db: Session, script_id: str) -> dict[str, Any]:
    """读取单剧本详情与事件；操作者授权由入口先完成，不写入或提交。"""
    return _script_detail_of(db, _script_record(db, script_id))


def latest_script_detail(db: Session, project_id: str) -> dict[str, Any] | None:
    """读取项目最新版本的详情；没有版本返回 None。"""
    script = latest_script(db, project_id)
    return _script_detail_of(db, script) if script is not None else None


def script_version_summaries(db: Session, project_id: str) -> list[dict[str, Any]]:
    """按版本倒序投影历史摘要，保持现有工作区响应字段。"""
    return [
        {
            "id": row.id,
            "version": row.version,
            "status": row.status,
            "title": row.title,
            "logline": row.logline,
            "approved": row.approved,
            "workspace_meta": deepcopy((row.content or {}).get("workspace_meta", {})),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in list_script_versions(db, project_id)
    ]
