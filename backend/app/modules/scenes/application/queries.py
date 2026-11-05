"""场景与当前档案读取。

调用方负责权限和同项目归属；查询不提交，ORM 结果继续依赖当前 Session。
canonical 是当前档案引用，不自动代表经审核的版本。
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.scenes.infrastructure.persistence.models import Scene, SceneProfile

logger = logging.getLogger(__name__)


def list_scenes(db: Session, project_id: str) -> list[Scene]:
    """按创建时间和名称读取项目场景，无匹配返回空列表；只读、不提交。"""
    return list(
        db.scalars(select(Scene).where(Scene.project_id == project_id).order_by(Scene.created_at, Scene.name))
    )


def scene_profile_of(db: Session, scene: Scene) -> SceneProfile | None:
    """按 canonical 引用读取场景当前档案，引用或记录缺失时返回 None。

    不筛选 approved，也不执行实体归属校验；不写入或提交。
    """
    if not scene.canonical_profile_id:
        return None
    return db.get(SceneProfile, scene.canonical_profile_id)


def scene_payload(db: Session, scene: Scene) -> dict:
    """读取当前档案并投影场景生成输入；缺失内容使用既有空值。

    仅查询，不提交；嵌套 JSON 按只读投影使用。
    """
    profile = scene_profile_of(db, scene)
    content = (profile.content if profile else {}) or {}
    return {
        "id": scene.id,
        "name": scene.name,
        "summary": scene.summary,
        "profile": content,
        "visual_prompt": content.get("visual_prompt", ""),
    }


def public_scene(db: Session, scene: Scene) -> dict:
    """将场景和当前档案投影为 API 字典；权限由调用方确认，不写入或提交。"""
    payload = scene_payload(db, scene)
    payload.update(
        {
            "canonical_profile_id": scene.canonical_profile_id,
            "approved_version": scene.approved_version,
            "chapter_index": scene.chapter_index,
        }
    )
    return payload
