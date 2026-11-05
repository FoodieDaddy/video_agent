"""人物实体、当前档案与数据投影查询。

调用方负责项目权限与实体归属。查询不写入、不提交；当前兼容接口返回 ORM 或字典。
canonical 指向当前选择，不等同于已审核版本；需要审批证据时应同时核对批准版本。
"""

from __future__ import annotations

import logging
from copy import deepcopy

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from studio_characters.contracts import (
    CharacterMetrics,
    CharacterReference,
    CharacterSnapshot,
    CharacterVoiceReference,
)
from studio_characters.infrastructure.persistence import queries as repository
from studio_characters.infrastructure.persistence.models import Character, CharacterProfile

logger = logging.getLogger(__name__)


def find_character_reference(db: Session, project_id: str, character_id: str) -> CharacterReference | None:
    """读取同项目人物身份；不存在或归属不符返回 None。"""
    character = db.get(Character, character_id)
    if character is None or character.project_id != project_id:
        return None
    return CharacterReference(id=character.id, project_id=character.project_id)


def portrait_asset_id(db: Session, character_id: str) -> str | None:
    """查询头像资产引用，沿用 approved 优先、版本倒序规则；不返回形象 ORM。"""
    return repository.preferred_portrait_asset_id(db, character_id)


def voice_reference(db: Session, character_id: str) -> CharacterVoiceReference | None:
    """读取人物声线 DTO；空 ID 或没有记录时返回 None。"""
    if not character_id:
        return None
    row = repository.first_voice(db, character_id)
    return CharacterVoiceReference(voice_id=row.voice_id) if row is not None else None


def character_metrics(db: Session, project_id: str) -> CharacterMetrics:
    """读取当前记录数量 DTO；不代表人物或图片的真实质量。"""
    return CharacterMetrics(*repository.count_character_records(db, project_id))


def character_detail_reference_matches(
    db: Session, *, project_id: str, character_id: str, kind: str, reference_id: str
) -> bool:
    """确认分镜服装/状态引用归属；错误映射由调用方按原有业务顺序执行。"""
    return repository.detail_reference_matches(
        db, project_id=project_id, character_id=character_id, kind=kind, reference_id=reference_id
    )


def list_characters(db: Session, project_id: str) -> list[Character]:
    """按创建时间和名称读取项目人物，无匹配返回空列表；只读、不提交。"""
    return list(
        db.scalars(
            select(Character)
            .where(Character.project_id == project_id)
            .order_by(Character.created_at, Character.name)
        )
    )


def list_character_snapshots(db: Session, project_id: str) -> list[CharacterSnapshot]:
    """沿用人物排序和当前档案投影，返回生成 payload 的深副本；不提交。"""
    return [
        CharacterSnapshot(
            id=character.id,
            project_id=character.project_id,
            name=character.name,
            generation_payload=deepcopy(character_payload(db, character)),
        )
        for character in list_characters(db, project_id)
    ]


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
