"""人物跨模块查询所需的持久化读取；不提交或修改记录。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    Character,
    CharacterAsset,
    CharacterCostume,
    CharacterProfile,
    CharacterState,
    CharacterVoice,
)


def preferred_portrait_asset_id(db: Session, character_id: str) -> str | None:
    """沿用已批准优先、版本降序的选择规则；没有头像时返回 None。"""
    row = db.scalar(
        select(CharacterAsset)
        .where(CharacterAsset.character_id == character_id, CharacterAsset.kind == "portrait")
        .order_by(CharacterAsset.approved.desc(), CharacterAsset.version.desc())
    )
    return row.asset_id if row is not None else None


def first_voice(db: Session, character_id: str) -> CharacterVoice | None:
    """读取当前任一已存声线，保留旧查询不附加排序的语义。"""
    return db.scalar(select(CharacterVoice).where(CharacterVoice.character_id == character_id))


def count_character_records(db: Session, project_id: str) -> tuple[int, int, int]:
    """返回项目人物、档案、形象记录数量，不筛选 approved 状态。"""
    return tuple(
        int(db.scalar(select(func.count(model.id)).where(model.project_id == project_id)) or 0)
        for model in (Character, CharacterProfile, CharacterAsset)
    )


def detail_reference_matches(
    db: Session, *, project_id: str, character_id: str, kind: str, reference_id: str
) -> bool:
    """读取服装或状态的归属；非法种类直接报告调用错误。"""
    if kind == "costume_id":
        model = CharacterCostume
    elif kind == "state_id":
        model = CharacterState
    else:
        raise ValueError(f"未知人物细节引用类型：{kind}")
    row = db.get(model, reference_id)
    return row is not None and row.project_id == project_id and row.character_id == character_id
