"""人物批准标记的写入归属；审核决定由 reviews 模块管理。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from studio_characters.infrastructure.persistence.models import Character, CharacterAsset
from studio_platform.exceptions import NotFoundError

from .queries import list_characters, profile_of


def _approve_profile(db: Session, character: Character) -> None:
    profile = profile_of(db, character)
    if profile is not None:
        profile.approved = True
        character.approved_version = profile.version
    character.status = "approved"


def approve_current_characters(db: Session, project_id: str) -> None:
    """批准当前档案及全部人物图片；调用方统一 flush，不提交。

    保留第一关的现有范围：没有冻结提审时版本，也不补算缺失 canonical 档案。
    """
    for character in list_characters(db, project_id):
        _approve_profile(db, character)
        for asset in db.scalars(select(CharacterAsset).where(CharacterAsset.character_id == character.id)):
            asset.approved = True


def approve_character_profile(db: Session, project_id: str, character_id: str) -> None:
    """核对项目后批准指定人物当前档案；不批准图片、不 flush、不提交。"""
    character = db.get(Character, character_id)
    if character is None or character.project_id != project_id:
        raise NotFoundError("人物不存在", details={"character_id": character_id})
    _approve_profile(db, character)


def approve_character_entity(db: Session, project_id: str, character: Character) -> Character:
    """兼容旧审核入口：操作传入同一实体并 flush；不提交、不批准图片。"""
    if character.project_id != project_id:
        raise NotFoundError("人物不存在", details={"character_id": character.id})
    _approve_profile(db, character)
    db.flush()
    return character
