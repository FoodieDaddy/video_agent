"""人物实体、当前档案与数据投影查询。

调用方负责项目权限与实体归属。查询不写入、不提交；当前兼容接口返回 ORM 或字典。
canonical 指向当前选择，不等同于已审核版本；需要审批证据时应同时核对批准版本。
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.character import Character, CharacterProfile

logger = logging.getLogger(__name__)


def list_characters(db: Session, project_id: str) -> list[Character]:
    """按创建时间和名称读取项目人物，无匹配返回空列表；只读、不提交。"""
    return list(
        db.scalars(
            select(Character)
            .where(Character.project_id == project_id)
            .order_by(Character.created_at, Character.name)
        )
    )


def profile_of(db: Session, character: Character) -> CharacterProfile | None:
    """按人物 canonical_profile_id 读取当前档案，无引用或记录缺失返回 None。

    不校验 approved 状态，也不替调用方验证人物归属；不写入或提交。
    """
    if not character.canonical_profile_id:
        return None
    return db.get(CharacterProfile, character.canonical_profile_id)


def character_payload(db: Session, character: Character) -> dict:
    """读取当前档案并投影人物生成输入，保留既有缺档案默认值。

    不改变数据库；部分嵌套 JSON 沿用 ORM 值，调用方应按只读结果使用。
    """
    profile = profile_of(db, character)
    return {
        "id": character.id,
        "name": character.name,
        "aliases": character.aliases or [],
        "role_type": character.role_type,
        "status": character.status,
        "summary": character.summary,
        "appearance_keywords": character.appearance_keywords or [],
        "profile": (profile.content if profile else {}) or {},
    }


def public_character(db: Session, character: Character) -> dict:
    """在人物输入投影上增加 API 所需身份、状态与版本字段。

    会查询当前档案，不提交；访问权限由调用方确认。
    """
    payload = character_payload(db, character)
    payload.update(
        {
            "canonical_profile_id": character.canonical_profile_id,
            "approved_version": character.approved_version,
            "meta": character.meta or {},
        }
    )
    return payload


def _profile_version(db: Session, character_id: str) -> int:
    """读取人物已有档案的最大版本并建议下一个编号。

    不预留编号、不加锁；并发版本分配仍需调用方协调。
    """
    current = db.scalar(
        select(func.max(CharacterProfile.version)).where(CharacterProfile.character_id == character_id)
    )
    return int(current or 0) + 1
