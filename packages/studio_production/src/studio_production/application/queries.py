"""制作计划、镜头与项目摘要查询。

调用方负责项目访问和所给实体归属；本文件不写入或提交。
默认读取最新版本而不自动限制 approved，返回 ORM 或兼容字典投影。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from studio_characters.public import list_character_snapshots
from studio_platform.exceptions import ConflictError, NotFoundError
from studio_production.infrastructure.persistence.models import (
    DirectingPlan,
    Shot,
    ShotCharacter,
    Storyboard,
)
from studio_projects.contracts import ProjectContext as Project
from studio_scenes.public import list_scene_snapshots
from studio_story.public import assert_script_baseline_reference, latest_script_snapshot

from .fingerprints import shot_edit_fingerprint

logger = logging.getLogger(__name__)


def latest_plan(db: Session, project_id: str) -> DirectingPlan | None:
    """按版本降序读取项目最新导演计划，无记录返回 None；不筛选审核状态。"""
    return db.scalar(
        select(DirectingPlan)
        .where(DirectingPlan.project_id == project_id)
        .order_by(DirectingPlan.version.desc())
    )


def get_directing_plan(db: Session, plan_id: str) -> DirectingPlan:
    """读取单一历史版本；API取得记录后仍须核对其项目权限。"""
    plan = db.get(DirectingPlan, plan_id)
    if plan is None:
        raise NotFoundError("导演规划版本不存在", details={"plan_id": plan_id})
    return plan


def directing_source_status(db: Session, plan: DirectingPlan) -> dict[str, Any]:
    """对照当前剧本判断历史来源；旧计划缺少指纹时返回unknown，不补造来源。"""
    source = (plan.content or {}).get("source_script")
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("id"), str)
        or not source["id"]
        or not isinstance(source.get("fingerprint"), str)
        or not source["fingerprint"]
    ):
        return {"source_script": source if isinstance(source, dict) else None, "source_status": "unknown"}
    try:
        # 共用查询会刷新ORM缓存，也能识别旧PATCH在同一ID上的内容变化。
        assert_script_baseline_reference(db, plan.project_id, source["id"], source["fingerprint"])
    except ConflictError:
        return {"source_script": source, "source_status": "stale"}
    return {"source_script": source, "source_status": "current"}


def latest_board(db: Session, project_id: str) -> Storyboard | None:
    """按版本降序读取项目最新分镜，无记录返回 None；只读、不提交。"""
    return db.scalar(
        select(Storyboard).where(Storyboard.project_id == project_id).order_by(Storyboard.version.desc())
    )


def list_shots(db: Session, project_id: str, *, board: Storyboard | None = None) -> list[Shot]:
    """读取给定分镜的镜头；board 为空时选项目最新分镜，无分镜则返回空列表。

    镜头按 order_index 排序；显式 board 的项目归属由调用方保证，不在此再次校验。
    """
    board = board or latest_board(db, project_id)
    if board is None:
        return []
    return list(db.scalars(select(Shot).where(Shot.storyboard_id == board.id).order_by(Shot.order_index)))


def shot_payload(db: Session, shot: Shot) -> dict:
    """将镜头及其人物关系、当前选择引用投影为生成输入字典。

    会查询镜头人物关系及项目人物名称，未知人物名使用空值；不写入或提交。
    selected 引用按现有字段值返回，不代表资产存在、媒体质量或审核已经满足。
    """
    characters = list(db.scalars(select(ShotCharacter).where(ShotCharacter.shot_id == shot.id)))
    names = {character.id: character.name for character in list_character_snapshots(db, shot.project_id)}
    return {
        "shot_id": shot.id,
        "order": shot.order_index,
        "scene_id": shot.scene_id,
        "description": shot.description,
        "action": shot.action,
        "camera": shot.camera or {},
        "characters": [
            {
                "character_id": ref.character_id,
                "character_name": names.get(ref.character_id, ""),
                "costume_id": ref.costume_id,
                "state_id": ref.state_id,
                "action": ref.action,
                "emotion": ref.emotion,
            }
            for ref in characters
        ],
        "dialogue": shot.dialogue or [],
        "duration_seconds": shot.duration_seconds,
        "visual_prompt": shot.visual_prompt,
        "negative_prompt": shot.negative_prompt,
        "reference_asset_ids": shot.reference_asset_ids or [],
        "video_asset_id": shot.selected_video_id,
        "audio_asset_id": shot.selected_audio_id,
        "approved": shot.approved,
    }


def public_shot(db: Session, shot: Shot) -> dict:
    """在镜头生成输入上附加 API 所需身份、状态和配置字段；只读，不提交。"""
    payload = shot_payload(db, shot)
    payload.update(
        {
            "id": shot.id,
            "storyboard_id": shot.storyboard_id,
            "status": shot.status,
            "approved": shot.approved,
            "config_version": shot.config_version,
            "prompt_version": shot.prompt_version,
            "edit_fingerprint": shot_edit_fingerprint(shot),
        }
    )
    return payload


def project_summary(db: Session, project: Project) -> dict[str, Any]:
    """聚合项目最新剧本、导演计划、分镜和实体名称为摘要。

    前置：project 已授权；返回当前读取结果而非版本快照或质量评分，不写入或提交。
    synopsis 的长度处理沿用现有规则；摘要不保证跨多条查询的并发快照一致性。
    """
    script = latest_script_snapshot(db, project.id)
    plan = latest_plan(db, project.id)
    board = latest_board(db, project.id)
    shots = list_shots(db, project.id)
    return {
        "project_id": project.id,
        "name": project.name,
        "language": project.language,
        "genre": project.genre,
        "status": project.status,
        "script_version": script.version if script else 0,
        "script_title": script.title if script else "",
        "logline": script.logline if script else "",
        "synopsis": (script.synopsis if script else "")[:1200],
        "directing_plan_version": plan.version if plan else 0,
        "visual_style": ((plan.content or {}).get("visual_style") if plan else ""),
        "storyboard_version": board.version if board else 0,
        "shot_count": len(shots),
        "characters": [character.name for character in list_character_snapshots(db, project.id)],
        "scenes": [scene.name for scene in list_scene_snapshots(db, project.id)],
        "total_duration_seconds": round(sum(shot.duration_seconds for shot in shots), 2),
    }
